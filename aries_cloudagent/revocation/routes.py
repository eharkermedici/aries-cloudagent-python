"""Revocation registry admin routes."""

from asyncio import shield

from aiohttp import web
from aiohttp_apispec import docs, request_schema, response_schema

from marshmallow import fields, Schema

from ..messaging.credential_definitions.util import CRED_DEF_SENT_RECORD_TYPE
from ..messaging.valid import INDY_CRED_DEF_ID
from ..storage.base import BaseStorage

from .error import RevocationNotSupportedError
from .indy import IndyRevocation
from .models.issuer_revocation_record import IssuerRevocationRecordSchema
from .models.revocation_registry import RevocationRegistry


class RevRegCreateRequestSchema(Schema):
    """Request schema for revocation registry creation request."""

    credential_definition_id = fields.Str(
        description="Credential definition identifier", **INDY_CRED_DEF_ID
    )

    max_cred_num = fields.Int(
        description="Maximum credential numbers", required=False
    )


class RevRegCreateResultSchema(Schema):
    """Result schema for revocation registry creation request."""

    result = IssuerRevocationRecordSchema()


class RevRegUpdateTailFileUriSchema(Schema):
    """Request schema for updating tail file URI."""

    tails_public_uri = fields.Url(
        description="Public URI to the tail file", required=True
    )


@docs(tags=["revocation"], summary="Creates a new revocation registry")
@request_schema(RevRegCreateRequestSchema())
@response_schema(RevRegCreateResultSchema(), 200)
async def revocation_create_registry(request: web.BaseRequest):
    """
    Request handler for creating a new revocation registry.

    Args:
        request: aiohttp request object

    Returns:
        The revocation registry identifier

    """
    context = request.app["request_context"]

    body = await request.json()

    credential_definition_id = body.get("credential_definition_id")
    max_cred_num = body.get("max_cred_num")

    # check we published this cred def
    storage = await context.inject(BaseStorage)
    found = await storage.search_records(
        type_filter=CRED_DEF_SENT_RECORD_TYPE,
        tag_query={"cred_def_id": credential_definition_id},
    ).fetch_all()
    if not found:
        raise web.HTTPNotFound()

    try:
        issuer_did = credential_definition_id.split(":")[0]
        revoc = IndyRevocation(context)
        registry_record = await revoc.init_issuer_registry(
            credential_definition_id, issuer_did, max_cred_num=max_cred_num
        )
    except RevocationNotSupportedError as e:
        raise web.HTTPBadRequest() from e
    await shield(
        registry_record.generate_registry(context, RevocationRegistry.get_temp_dir())
    )

    return web.json_response({"result": registry_record.serialize()})


@docs(tags=["revocation"], summary="Get current revocation registry",
      parameters=[{
          "in": "path",
          "name": "id",
          "description": "use credential definition id as the revocation registry id."
      }])
@response_schema(RevRegCreateResultSchema(), 200)
async def get_current_registry(request: web.BaseRequest):
    """
    Request handler for getting the current revocation registry.

    Args:
        request: aiohttp request object

    Returns:
        The revocation registry identifier

    """
    context = request.app["request_context"]

    credential_definition_id = request.match_info["id"]

    # check we published this cred def
    storage = await context.inject(BaseStorage)
    found = await storage.search_records(
        type_filter=CRED_DEF_SENT_RECORD_TYPE,
        tag_query={"cred_def_id": credential_definition_id},
    ).fetch_all()
    if not found:
        raise web.HTTPNotFound()

    try:
        revoc = IndyRevocation(context)
        registry_record = await revoc.get_active_issuer_revocation_record(
            credential_definition_id
        )
    except RevocationNotSupportedError as e:
        raise web.HTTPBadRequest() from e

    return web.json_response({"result": registry_record.serialize()})

@docs(tags=["revocation"], summary="Get the tail file of revocation registry",
      produces="application/octet-stream",
      parameters=[{
          "in": "path",
          "name": "id",
          "description": "use credential definition id as the revocation registry id."
      }],
      responses={
          200: {
              "description": "tail file",
              "schema": {
                  "type": "file"
              }
          }
      })
async def get_tail_file(request: web.BaseRequest) -> web.FileResponse:
    """
    Request handler for getting the tail file of the revocation registry.

    Args:
        request: aiohttp request object

    Returns:
        The tail file in FileResponse

    """
    context = request.app["request_context"]

    credential_definition_id = request.match_info["id"]

    # check we published this cred def
    storage = await context.inject(BaseStorage)
    found = await storage.search_records(
        type_filter=CRED_DEF_SENT_RECORD_TYPE,
        tag_query={"cred_def_id": credential_definition_id},
    ).fetch_all()
    if not found:
        raise web.HTTPNotFound()

    try:
        revoc = IndyRevocation(context)
        registry_record = await revoc.get_active_issuer_revocation_record(
            credential_definition_id
        )
    except RevocationNotSupportedError as e:
        raise web.HTTPBadRequest() from e

    return web.FileResponse(path=registry_record.tails_local_path, status=200)


@docs(tags=["revocation"], summary="Publish a given revocation registry",
      parameters=[{
          "in": "path",
          "name": "id",
          "description": "use credential definition id as the revocation registry id."
      }])
@response_schema(RevRegCreateResultSchema(), 200)
async def publish_registry(request: web.BaseRequest):
    """
    Request handler for publishing a revocation registry based on the registry id.

    Args:
        request: aiohttp request object

    Returns:
        The revocation registry record

    """
    context = request.app["request_context"]

    credential_definition_id = request.match_info["id"]

    # check we published this cred def
    storage = await context.inject(BaseStorage)
    found = await storage.search_records(
        type_filter=CRED_DEF_SENT_RECORD_TYPE,
        tag_query={"cred_def_id": credential_definition_id},
    ).fetch_all()
    if not found:
        raise web.HTTPNotFound()

    try:
        revoc_registry = await IndyRevocation(context).get_active_issuer_revocation_record(credential_definition_id)
    except RevocationNotSupportedError as e:
        raise web.HTTPBadRequest() from e

    await revoc_registry.publish_registry_definition(context)
    print("published registry definition")
    await revoc_registry.publish_registry_entry(context)
    print("published registry entry")

    return web.json_response({"result": revoc_registry.serialize()})


@docs(tags=["revocation"], summary="Update revocation registry with new public URI to the tail file.",
      parameters=[{
          "in": "path",
          "name": "id",
          "description": "use credential definition id as the revocation registry id."
      }])
@request_schema(RevRegUpdateTailFileUriSchema())
@response_schema(RevRegCreateResultSchema(), 200)
async def update_registry(request: web.BaseRequest):
    """
    Request handler for updating a revocation registry based on the registry id.

    Args:
        request: aiohttp request object

    Returns:
        The revocation registry record

    """
    context = request.app["request_context"]

    credential_definition_id = request.match_info["id"]

    body = await request.json()

    tails_public_uri = body.get("tails_public_uri")

    try:
        revoc = IndyRevocation(context)
        registry_record = await revoc.get_active_issuer_revocation_record(
            credential_definition_id
        )
    except RevocationNotSupportedError as e:
        raise web.HTTPBadRequest() from e

    registry_record.set_tail_file_public_uri(tails_public_uri)
    await registry_record.save(context, reason="Updating tail file public URI.")

    return web.json_response({"result": registry_record.serialize()})

async def register(app: web.Application):
    """Register routes."""
    app.add_routes(
        [
            web.post("/revocation/create-registry", revocation_create_registry),
            web.get("/revocation/registry/{id}", get_current_registry),
            web.get("/revocation/registry/{id}/tail-file", get_tail_file),
            web.patch("/revocation/registry/{id}", update_registry),
            web.post("/revocation/registry/{id}/publish", publish_registry),
        ]
    )

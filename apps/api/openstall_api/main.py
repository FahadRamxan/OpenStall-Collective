"""FastAPI entry point. Run with: uvicorn openstall_api.main:app --reload"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from openstall_api import __version__
from openstall_api.settings import get_settings
from openstall_api.status import router as status_router
from openstall_api.storefront import storefront, storefront_http_app

settings = get_settings()
mcp_http = storefront_http_app(settings)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # The MCP app's own lifespan does not run inside FastAPI, so start its session manager here.
    async with storefront.session_manager.run():
        yield


app = FastAPI(title="OpenStall Collective API", version=__version__, lifespan=lifespan)

# The web app calls the API from the browser, from another origin. Allow that origin and no other.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.WEB_BASE_URL],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(status_router)

# Add the MCP route itself rather than mounting the app, so the endpoint is exactly /mcp, not /mcp/.
app.router.routes.extend(mcp_http.routes)

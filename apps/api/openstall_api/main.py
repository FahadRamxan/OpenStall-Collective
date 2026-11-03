"""FastAPI entry point. Run with: uvicorn openstall_api.main:app --reload"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from openstall_api import __version__
from openstall_api.adapters import get_registry
from openstall_api.catalog_api import router as catalog_router
from openstall_api.chat_api import router as chat_router
from openstall_api.db import REPO_ROOT, migrate
from openstall_api.dev_api import router as dev_router
from openstall_api.events_api import router as events_router
from openstall_api.fake_paypal_api import router as fake_paypal_router
from openstall_api.media_api import router as media_router
from openstall_api.orders_api import router as orders_router
from openstall_api.seller_chat_api import router as seller_chat_router
from openstall_api.settings import get_settings
from openstall_api.status import router as status_router
from openstall_api.webhooks_api import router as webhooks_router
from openstall_api.whatsapp_api import router as whatsapp_router
from openstall_api.storefront import storefront, storefront_http_app

settings = get_settings()
mcp_http = storefront_http_app(settings)


def migrate_if_enabled() -> bool:
    """Bring the database up to date when AUTO_MIGRATE is on. Returns whether it ran."""
    if not get_settings().AUTO_MIGRATE:
        return False
    migrate()
    return True


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Before serving, since any request may need the tables. Alembic is synchronous, so keep it off the event loop.
    await run_in_threadpool(migrate_if_enabled)
    # The MCP app's own lifespan does not run inside FastAPI, so start its session manager here.
    async with storefront.session_manager.run():
        yield
    # Close the PayPal clients' connection pools on shutdown.
    get_registry().close()


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
app.include_router(events_router)
app.include_router(catalog_router)
app.include_router(orders_router)
app.include_router(fake_paypal_router)
app.include_router(dev_router)
app.include_router(media_router)
app.include_router(webhooks_router)
app.include_router(whatsapp_router)
app.include_router(chat_router)
app.include_router(seller_chat_router)

# The seed photos (placeholders until the team adds its own), and the photos and voice notes sellers send.
app.mount("/media/seed", StaticFiles(directory=REPO_ROOT / "assets" / "seed"), name="seed-media")

# Add the MCP route itself rather than mounting the app, so the endpoint is exactly /mcp, not /mcp/.
app.router.routes.extend(mcp_http.routes)

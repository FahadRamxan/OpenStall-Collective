"""FastAPI entry point. Run with: uvicorn openstall_api.main:app --reload"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from openstall_api import __version__
from openstall_api.adapters import get_registry
from openstall_api.catalog_api import router as catalog_router
from openstall_api.chat_api import router as chat_router
from openstall_api.dashboard_api import router as dashboard_router
from openstall_api.db import REPO_ROOT, migrate
from openstall_api.demo_api import router as demo_router
from openstall_api.dev_api import router as dev_router
from openstall_api.limits import LimitsMiddleware, TooMany
from openstall_api.doctor import router as doctor_router
from openstall_api.events_api import router as events_router
from openstall_api.fake_paypal_api import router as fake_paypal_router
from openstall_api.feeds_api import router as feeds_router
from openstall_api.guardrails_api import router as guardrails_router
from openstall_api.media_api import SeedPhotos
from openstall_api.media_api import router as media_router
from openstall_api.offers_api import router as offers_router
from openstall_api.orders_api import router as orders_router
from openstall_api.quotes_api import router as quotes_router
from openstall_api.passports_api import router as passports_router
from openstall_api.search_api import router as search_router
from openstall_api.seller_chat_api import router as seller_chat_router
from openstall_api.stall_api import router as stall_router
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

# Security and abuse limits, body sizes and security headers (limits.py). Added before CORS, so CORS wraps it and a
# 429 still reaches the web app with its CORS headers.
app.add_middleware(LimitsMiddleware)


@app.exception_handler(TooMany)
def too_many(request: Request, error: TooMany) -> JSONResponse:
    """A limit reached in code (a quote request, an agent run, a seller's messages): 429, with when to retry."""
    return JSONResponse({"detail": str(error)}, status_code=429, headers={"Retry-After": str(error.retry_after)})


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
app.include_router(doctor_router)
app.include_router(events_router)
app.include_router(catalog_router)
app.include_router(search_router)
app.include_router(demo_router)
app.include_router(guardrails_router)
app.include_router(dashboard_router)
app.include_router(stall_router)
app.include_router(offers_router)
app.include_router(quotes_router)
app.include_router(orders_router)
app.include_router(fake_paypal_router)
app.include_router(dev_router)
app.include_router(media_router)
app.include_router(webhooks_router)
app.include_router(whatsapp_router)
app.include_router(chat_router)
app.include_router(seller_chat_router)
# For agents, at the root like /mcp: /catalog.json, /catalog/{product_id}.json, /llms.txt and /passport/{seller_id}.
app.include_router(feeds_router)
app.include_router(passports_router)

# The seed photos (placeholders until the team adds its own), with caching headers. The photos and voice notes
# sellers send are media_router's /media/uploads/{key}.
app.mount("/media/seed", SeedPhotos(directory=REPO_ROOT / "assets" / "seed"), name="seed-media")

# Add the MCP route itself rather than mounting the app, so the endpoint is exactly /mcp, not /mcp/.
app.router.routes.extend(mcp_http.routes)

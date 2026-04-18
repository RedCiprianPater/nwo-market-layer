"""
Mount Layer 6 into the Layer 5 gateway.

Option A — inline mount (Layer 5 and Layer 6 in the same process):
In your Layer 5 src/api/main.py, add:

    from nwo_market_layer6.src.api.main import market_app
    app.mount("/", market_app)

Option B — sidecar proxy (separate processes, recommended for production):
Set LAYER6_URL=http://localhost:8006 in Layer 5 .env, then add this
proxy route in Layer 5 src/api/routes.py:

    @router.api_route("/market/{path:path}", methods=["GET","POST","PUT","DELETE"])
    async def proxy_market(request: Request, path: str):
        return await proxy_request(6_placeholder, f"/v1/market/{path}", request)

Or use Nginx/Caddy upstream for zero-code routing.
"""
print(__doc__)

import logging
from aiohttp import web
import config
import database as db
from worker_manager import worker_manager

logger = logging.getLogger("nft_bot.internal_api")

routes = web.RouteTableDef()

@routes.get("/status")
@routes.get("/api/status")
async def handle_status(request):
    return web.json_response({
        "ok": True,
        "service": "NFTtelegram Engine",
        "status": "online",
        "main_bot": getattr(config, "MAIN_BOT_USERNAME", ""),
        "deal_bot": getattr(config, "DEAL_BOT_USERNAME", ""),
        "active_workers_count": len(worker_manager.active_bots),
        "timestamp": db.now_utc_str()
    })

@routes.post("/api/worker/start")
async def handle_start_worker(request):
    try:
        data = await request.json()
        user_id = int(data.get("user_id", 0))
        token = str(data.get("token", "")).strip()

        if not user_id or not token:
            return web.json_response({
                "ok": False,
                "error": "user_id and token are required"
            }, status=400)

        ok, result = await worker_manager.start_worker(user_id=user_id, token=token)
        if ok:
            return web.json_response({
                "ok": True,
                "bot_username": result,
                "user_id": user_id
            })
        else:
            return web.json_response({
                "ok": False,
                "error": result
            }, status=400)
    except Exception as e:
        logger.error(f"Error in handle_start_worker: {e}")
        return web.json_response({"ok": False, "error": str(e)}, status=500)

@routes.post("/api/worker/stop")
async def handle_stop_worker(request):
    try:
        data = await request.json()
        user_id = int(data.get("user_id", 0))
        token = str(data.get("token", "")).strip()
        bot_id = int(data.get("bot_id", 0))

        if not user_id and not token and not bot_id:
            return web.json_response({"ok": False, "error": "user_id, bot_id or token is required"}, status=400)

        stopped = await worker_manager.stop_worker(user_id=user_id, token=token, bot_id=bot_id, remove_from_db=False)
        return web.json_response({
            "ok": True,
            "message": "Worker stopped",
            "stopped": stopped
        })
    except Exception as e:
        logger.error(f"Error in handle_stop_worker: {e}")
        return web.json_response({"ok": False, "error": str(e)}, status=500)

@routes.get("/api/worker/list")
async def handle_list_workers(request):
    try:
        workers = await db.get_all_active_worker_bots()
        active_ids = set(worker_manager.active_bots.keys())
        result = []
        for w in workers:
            uid = w.get("user_id")
            result.append({
                "user_id": uid,
                "bot_username": w.get("bot_username"),
                "bot_id": w.get("bot_id"),
                "is_running": uid in active_ids
            })
        return web.json_response({
            "ok": True,
            "workers": result
        })
    except Exception as e:
        logger.error(f"Error in handle_list_workers: {e}")
        return web.json_response({"ok": False, "error": str(e)}, status=500)

@routes.get("/api/stats")
async def handle_stats(request):
    try:
        active_deals = await db.get_active_pending_deals()
        active_workers = len(worker_manager.active_bots)
        return web.json_response({
            "ok": True,
            "active_deals_count": len(active_deals),
            "active_workers_count": active_workers,
            "main_bot": getattr(config, "MAIN_BOT_USERNAME", "")
        })
    except Exception as e:
        logger.error(f"Error in handle_stats: {e}")
        return web.json_response({"ok": False, "error": str(e)}, status=500)

async def create_internal_app():
    app = web.Application()
    app.add_routes(routes)
    return app

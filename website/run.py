import os
import sys
from pathlib import Path

# Add current directory to path
current_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(current_dir))

import uvicorn
import config

if __name__ == "__main__":
    host = getattr(config, "WEB_HOST", "0.0.0.0")
    port = getattr(config, "WEB_PORT", 8080)
    print("\n" + "=" * 60)
    print(f" 🌐 Standalone NFT Deals Website")
    print(f" URL: http://localhost:{port}")
    print("=" * 60 + "\n")
    uvicorn.run("server:app", host=host, port=port, reload=True)

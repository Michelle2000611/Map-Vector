import uvicorn
import os,socket
from mapvector.configuration.settings import Settings
from mapvector.configuration.runtime import configure_runtime

if __name__ == '__main__':
    port=int(os.environ.get('MAPVECTOR_API_PORT','8840'));settings=Settings(api_port=port)
    configure_runtime(settings.project_root)
    try:
        with socket.socket() as listener:listener.bind(('127.0.0.1',port))
    except OSError as exc:raise SystemExit('Map-Vector API port '+str(port)+' is occupied. Stop the owning service or set MAPVECTOR_API_PORT.') from exc
    uvicorn.run('mapvector.api.app:create_app', factory=True, host='127.0.0.1', port=port)

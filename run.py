"""
Turnificator9000 — entry point dell'applicazione Flask.

Avvio sviluppo:
    python run.py

Avvio produzione (esempio con gunicorn):
    gunicorn -k geventwebsocket.gunicorn.workers.GeventWebSocketWorker \
             -w 1 -b 0.0.0.0:5000 "app:create_app()"
"""

import os

# Importa la factory e crea l'app
import app as app_pkg
application = app_pkg.create_app()
sio = app_pkg.socketio

if __name__ == '__main__':
    debug = os.environ.get('FLASK_DEBUG', '0') == '1'
    sio.run(
        application,
        host='0.0.0.0',
        port=5000,
        debug=debug,
        allow_unsafe_werkzeug=True,
    )

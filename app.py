from flask import Flask
from config import Config
from utils.logger import setup_logger
from routes.routes import configure_routes  
from werkzeug.middleware.proxy_fix import ProxyFix

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)
    app.config['SITEMAP_URL_SCHEME'] = 'https'

    # Setup Logging
    logger = setup_logger('app_logger',app.config['LOG_PATH'])
    app.logger.addHandler(logger)
    
    # Configure Routes
    configure_routes(app)

    return app

app = create_app()  # This line added

if __name__ == '__main__':
    app.run()

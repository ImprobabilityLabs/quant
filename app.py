from flask import Flask
from config import Config
from models import db 
from utils.logger import setup_logger
from routes.routes import configure_routes  
from werkzeug.middleware.proxy_fix import ProxyFix
import stripe

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)
    app.config['SITEMAP_URL_SCHEME'] = 'https'
    
    # Initialize Extensions
    db.init_app(app)

    # Setup Logging
    logger = setup_logger('app_logger',app.config['LOG_PATH'])
    app.logger.addHandler(logger)
    
    # Set Stripe API Key
    stripe.api_key = app.config['STRIPE_API_KEY']

    # Configure Routes
    configure_routes(app)

    # Create tables if they do not exist
    with app.app_context():
        db.create_all()
        
    return app

app = create_app()  # This line added

if __name__ == '__main__':
    app.run()

from flask import Flask, render_template, request, redirect, url_for, session, jsonify, abort, current_app, Response
from flask_sitemap import Sitemap
from utils.utility import *
import openai
from datetime import datetime
from meta_tags import MetaTags

def configure_routes(app):

    sitemap = Sitemap(app=app)

    @app.context_processor
    def inject_analytics():
        return dict(
            google_analytics_id=app.config['GOOGLE_ANALYTICS_ID'],
            google_site_verification=app.config['GOOGLE_SITE_VERIFICATION'],
            bing_site_verification=app.config['BING_SITE_VERIFICATION']
        )

    @app.after_request
    def add_header(response):
        # Ensure the endpoint is not None before checking its value
        if request.endpoint and 'static' not in request.endpoint:
            response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
            response.headers['Pragma'] = 'no-cache'
            response.headers['Expires'] = '0'
        return response
    
    @app.route('/robots.txt')
    def robots_txt():
        base_url = request.url_root[:-1]  # Remove the trailing slash
        lines = [
            "User-Agent: *",
            "Allow: /",
            "Allow: /contact",
            f"Sitemap: {base_url}/sitemap.xml"
        ]
        return Response("\n".join(lines), mimetype="text/plain")

    @app.route('/', methods=['GET', 'POST'])
    def index_page():
        current_app.logger.info('Info: Index Page - Member Object: ' + str(member))
        return render_template('index.html', seometa=MetaTags)

    @app.route('/contact', methods=['GET', 'POST'])
    def contact_page():
        current_app.logger.info('Info: Contact Page - Member Object: ' + str(member))
        return render_template('contact.html', seometa=MetaTags)

    @sitemap.register_generator
    def index():
        yield 'index_page', {}

    @sitemap.register_generator
    def contact():
        yield 'contact_page', {}     


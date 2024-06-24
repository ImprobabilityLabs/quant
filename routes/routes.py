from flask import Flask, render_template, request, redirect, url_for, session, jsonify, abort, current_app, Response
from flask_sitemap import Sitemap
from models import db, User, Subscription, MobileNumber, History, UserPreference, AssistantPreference 
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
        referrer = request.args.get('referrer')
        if referrer:
            session['referrer'] = referrer
            current_app.logger.info(f'Referrer set to: {referrer}')
        if session.get('user_provider_id'):
            member = check_user_subscription(session.get('user_provider_id'))
            is_user = member['is_user']
        else:
            member = check_user_subscription(None)
            is_user = False
        product_data = get_products()
        current_app.logger.info('Info: Index Page - Member Object: ' + str(member))
        menu = generate_menu(member)
        return render_template('index.html', seometa=MetaTags, menu=menu, is_user=is_user, products=product_data)

    @app.route('/contact', methods=['GET', 'POST'])
    def contact_page():
        if session.get('user_provider_id'):
            member = check_user_subscription(session.get('user_provider_id'))
        else:
            member = check_user_subscription(None)
        current_app.logger.info('Info: Contact Page - Member Object: ' + str(member))
        menu = generate_menu(member)
        return render_template('contact.html', seometa=MetaTags, menu=menu)

    @sitemap.register_generator
    def index():
        yield 'index_page', {}

    @sitemap.register_generator
    def contact():
        yield 'contact_page', {}     


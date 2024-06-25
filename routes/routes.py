from flask import Flask, render_template, request, redirect, url_for, session, jsonify, abort, current_app, Response
from flask_sitemap import Sitemap
from utils.utility import get_stock_data, check_openai_key, open_ai_anaysis
import openai
import pandas as pd
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
        error = None
        api_error = None
        stock_error = None
        input_error = None
        openai_error = None
        output_analysis = None
        if request.method == 'POST':
            current_app.logger.info('Received POST request with following form data:')
            for key in request.form:
                current_app.logger.info(f'{key}: {request.form[key]}')
            # Validate form data
            required_fields = [
                'api-key', 'ai-model', 'stock-ticker', 'stock-period'
            ]
            if not all(field in request.form for field in required_fields):
                error = True
                input_error = 'Please complete all required fields.'
            api_key = request.form.get('api-key')
            ticker = request.form.get('stock-ticker')
            period = request.form.get('stock-period')
            model = request.form.get('ai-model')
            if (api_key is None or api_key == '') or not check_openai_key(api_key):
                error = True
                api_error = 'Invalid or Missing API Key. Please enter a valid API key.'   
            if not error:
                data, success, message = get_stock_data(ticker, period)
                if not success:
                    error = True
                    stock_error = message
                else:
                    datacsv = data.to_csv()
                    output_analysis, openai_error = open_ai_anaysis(api_key, model, ticker, datacsv)
                    if openai_error:
                        error = True
                    current_app.logger.info(f'index --> output_analysis: {output_analysis}')
        return render_template('index.html', seometa=MetaTags, output_analysis=output_analysis, form_data=request.form, error=error, openai_error=openai_error, api_error=api_error, stock_error=stock_error, input_error=input_error)

    @app.route('/contact', methods=['GET', 'POST'])
    def contact_page():
        return render_template('contact.html', seometa=MetaTags)

    @sitemap.register_generator
    def index():
        yield 'index_page', {}

    @sitemap.register_generator
    def contact():
        yield 'contact_page', {}     


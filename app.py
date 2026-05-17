from flask import Flask, jsonify
from flask_cors import CORS
from config import Config

# Import blueprints
from auth.routes import auth_bp
from chat.routes import chat_bp
from direct_chat.routes import direct_chat_bp
from users.routes import users_bp

# Import DB init (runs schema creation on startup)
import db.database  # noqa: F401


def create_app():
    """
    Flask app factory.
    Creates, configures, and returns the Flask application.
    """
    app = Flask(__name__)
    app.config['SECRET_KEY'] = Config.SECRET_KEY

    # --- CORS ---
    # Allow requests from Flutter web and any local dev origin.
    # In production, replace '*' with your actual Flutter web domain.
    CORS(app, resources={
        r"/*": {
            "origins": "*",
            "methods": ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
            "allow_headers": ["Content-Type", "Authorization"]
        }
    })

    # --- Register Blueprints ---
    app.register_blueprint(auth_bp)
    app.register_blueprint(chat_bp)
    app.register_blueprint(direct_chat_bp)
    app.register_blueprint(users_bp)

    # --- Health Check ---
    @app.route('/health', methods=['GET'])
    def health():
        """Simple liveness probe. Flutter can ping this on startup."""
        return jsonify({
            'success': True,
            'data': {
                'status': 'online',
                'name': 'Amai Yuki API',
                'version': '1.0.0'
            },
            'error': None
        })

    # --- Global 404 Handler ---
    @app.errorhandler(404)
    def not_found(e):
        return jsonify({'success': False, 'data': None, 'error': 'Endpoint not found'}), 404

    # --- Global 405 Handler ---
    @app.errorhandler(405)
    def method_not_allowed(e):
        return jsonify({'success': False, 'data': None, 'error': 'Method not allowed'}), 405

    # --- Global 500 Handler ---
    @app.errorhandler(500)
    def internal_error(e):
        return jsonify({'success': False, 'data': None, 'error': 'Internal server error'}), 500

    # --- Start Background Scheduler ---
    import os
    if os.environ.get('WERKZEUG_RUN_MAIN') == 'true' or not app.debug:
        from memory.manager import start_scheduler
        start_scheduler()

    return app


# --- Entry Point ---
if __name__ == '__main__':
    app = create_app()
    
    print("="*50)
    print("  Amai Yuki API — Starting Up")
    print("  http://localhost:5000")
    print("  Health: http://localhost:5000/health")
    print("="*50)
    
    app.run(
        host='0.0.0.0',
        port=5000,
        debug=True
    )

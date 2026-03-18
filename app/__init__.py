import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate

db = SQLAlchemy()
migrate = Migrate()


def create_app():
    app = Flask(__name__, instance_relative_config=True)

    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///pidex.db"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    db.init_app(app)
    migrate.init_app(app, db)

    from app.routes.home import home_bp
    from app.routes.cards import cards_bp
    from app.routes.collection import collection_bp
    from app.routes.binders import binders_bp
    from app.routes.sets import sets_bp

    app.register_blueprint(home_bp)
    app.register_blueprint(cards_bp)
    app.register_blueprint(collection_bp)
    app.register_blueprint(binders_bp)
    app.register_blueprint(sets_bp)

    with app.app_context():
        from app import models  # noqa: F401

    # Serve images locally in development — on the Pi this is handled by Nginx
    if app.debug:
        from flask import send_from_directory
        images_dir = os.path.join(app.root_path, '..', 'images')

        @app.route('/images/<path:filename>')
        def serve_images(filename):
            return send_from_directory(images_dir, filename)

    return app
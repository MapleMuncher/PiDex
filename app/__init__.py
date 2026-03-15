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

    from app.routes.cards import cards_bp
    from app.routes.collection import collection_bp
    from app.routes.binders import binders_bp
    from app.routes.pokemon import pokemon_bp

    app.register_blueprint(cards_bp)
    app.register_blueprint(collection_bp)
    app.register_blueprint(binders_bp)
    app.register_blueprint(pokemon_bp)

    return app
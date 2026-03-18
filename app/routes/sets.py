from flask import Blueprint, render_template

sets_bp = Blueprint("sets", __name__, url_prefix="/sets")


@sets_bp.route("/")
def index():
    return render_template("sets/index.html")
 
 
@sets_bp.route("/<set_id>")
def detail(set_id):
    return render_template("sets/detail.html", set_id=set_id)
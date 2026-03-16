import re
import sys
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).parent
_PROJECT_DIR = _SCRIPTS_DIR.parent
sys.path.insert(0, str(_PROJECT_DIR))

from app import create_app, db
from app.models import Series, Set


def _series_id_from_set_id(set_id: str) -> str:
    base = re.sub(r"\d+$", "", set_id)
    if base == set_id and set_id.endswith("p"):
        base = base[:-1]
    return base or set_id


def fix_series() -> None:
    app = create_app()
    with app.app_context():
        for set_ in Set.query.all():
            correct_id = _series_id_from_set_id(set_.id)
            if set_.series_id == correct_id:
                continue

            print(f"  {set_.id}: {set_.series_id!r} → {correct_id!r}")

            correct_series = db.session.get(Series, correct_id)
            if correct_series is None:
                correct_series = Series(id=correct_id, name=set_.series.name)
                db.session.add(correct_series)
                db.session.flush()

            set_.series_id = correct_id

        for series in Series.query.all():
            if not series.sets:
                print(f"  Deleting orphaned series: {series.id!r} ({series.name!r})")
                db.session.delete(series)

        db.session.commit()
        print("Done.")


if __name__ == "__main__":
    fix_series()
"""Create a demo database with FAKE data and generate one full PDF set.

    python scripts/make_demo.py [data-folder]

Default folder: ./demo-data (separate from the real ./data). Useful to see the app working
before entering real cases.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from docautomate.app import create_app  # noqa: E402
from docautomate.db import get_db  # noqa: E402

OBOSNOVKA = """ПРИМЕР ЕООД стопанисва склад за строителни материали в гр. София, кв. Примерен, ул. Тестова 5.
За нормалната работа на склада дружеството се нуждае от служител, който да извършва товаро-разтоварни и общи помощни дейности.
Въпреки търсенето на подходящи работници на местния и националния пазар на труда, дружеството среща затруднения при намирането на кандидати.
Предложеният гражданин на трета държава е запознат с характера на работата и е заявил готовност да я изпълнява."""

DUTIES = """Извършва товарене, разтоварване и пренасяне на материали.
Подрежда материалите и инвентара на определените места.
Поддържа чистотата и реда в работните площи.
Изпълнява и други задачи, възложени от прекия ръководител."""


def main():
    data = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("demo-data")
    app = create_app(data_dir=data)
    with app.app_context():
        d = get_db()
        if d.execute("SELECT count(*) FROM \"case\"").fetchone()[0] == 0:
            eid = d.execute(
                "INSERT INTO employer (name, eik, address, rep_name, rep_role, rep_gender, rep_egn, phone, email)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                ("ПРИМЕР ЕООД", "200000000", "гр. София, р-н Примерен, ул. Тестова 10", "Георги Иванов Петров",
                 "управител", "M", "0000000000", "+359888000000", "office@example.bg")).lastrowid
            pid = d.execute(
                "INSERT INTO position (employer_id, title, title_ru, nkpd, occupation_class, workplace, reporting_line,"
                " obosnovka, dh_purpose, dh_duties, dh_responsibilities, dh_rights, dh_requirements, dh_conditions)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (eid, "Общ работник", "Подсобный рабочий", "96220001", "неквалифицирани работници",
                 "Склад „Пример“, гр. София, ул. Тестова 5", "Управителя на дружеството", OBOSNOVKA,
                 "Общият работник извършва помощни и общи дейности в склада.", DUTIES,
                 "Точното и своевременно изпълнение на задачите.\nСпазването на трудовата дисциплина.",
                 "Да получава договореното възнаграждение.\nДа работи при безопасни условия.",
                 "способност за физическа работа;\nумение за работа в екип.",
                 "Работата се извършва в закрити помещения и на открито.")).lastrowid
            uzb = d.execute("SELECT id FROM country WHERE iso3='UZB'").fetchone()[0]
            cid = d.execute(
                "INSERT INTO candidate (name_cyr, name_lat, gender, birth_date, birth_place, birth_country_id,"
                " citizenship_id, passport_no, passport_issue_date, passport_expiry, phone)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                ("Иванов Петър Сергеевич", "Ivanov Petr Sergeevich", "M", "1985-01-01", "Tashkent Region", uzb, uzb,
                 "AB1234567", "2020-03-15", "2030-03-14", "0888123456")).lastrowid
            ct = d.execute("SELECT id FROM case_type WHERE legal_ground='24и' AND is_extension=0").fetchone()[0]
            d.execute(
                'INSERT INTO "case" (candidate_id, employer_id, position_id, case_type_id, contract_months,'
                " probation_months, salary, currency, pay_day, leave_days, extra_leave_days, notice_months,"
                " notification_email, staff_count, foreign_staff_count, doc_city, directorate)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (cid, eid, pid, ct, 36, 6, "1077", "евро", "30", 20, 0, 3, "office@example.bg", "25", "3", "София",
                 "дирекция „Миграция“ – МВР"))
            d.commit()
        case_id = d.execute('SELECT id FROM "case" ORDER BY id LIMIT 1').fetchone()[0]
        gen_id, errors = app.generate_case(case_id)
        folder = d.execute("SELECT folder FROM generation WHERE id=?", (gen_id,)).fetchone()[0]
        print("Готово:", data / "generated" / folder)
        for e in errors:
            print("Грешка:", e)
        return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())

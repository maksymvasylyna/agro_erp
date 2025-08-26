from flask import Blueprint, render_template, redirect, url_for, request, flash, current_app
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from extensions import db
from modules.reference.fields.field_models import Field
from modules.reference.fields.forms import FieldForm, FieldFilterForm

# Опційні залежності (якщо відсутні у проєкті — пропускаємо кроки)
try:
    from modules.purchases.payer_allocation.models import PayerAllocation  # щоб відв'язати field_id при wipe
except Exception:
    PayerAllocation = None

try:
    from modules.plans.models import Plan  # якщо нема — пропустимо видалення планів при wipe
except Exception:
    Plan = None

# У твоєму проєкті ApprovedPlan відсутній — залишаємо як None
ApprovedPlan = None

fields_bp = Blueprint('fields', __name__, template_folder='templates')


def _id(x):
    """Повертає .id для об'єктів або саме значення для SelectField(coerce=int)."""
    return getattr(x, "id", x) if x is not None else None


@fields_bp.route('/fields')
def index():
    form = FieldFilterForm(request.args)
    query = Field.query

    if form.cluster.data:
        query = query.filter_by(cluster_id=_id(form.cluster.data))
    if form.company.data:
        query = query.filter_by(company_id=_id(form.company.data))
    if form.culture.data:
        query = query.filter_by(culture_id=_id(form.culture.data))

    fields = query.all()
    return render_template(
        'fields/index.html',
        form=form,
        items=fields,
        create_url=url_for('fields.create')
    )


@fields_bp.route('/fields/create', methods=['GET', 'POST'])
def create():
    form = FieldForm()
    if form.validate_on_submit():
        # Нормалізуємо назву (прибираємо зайві пробіли), порівнюємо без регістру
        name = " ".join((form.name.data or "").split())
        cluster_id = _id(form.cluster.data)
        company_id = _id(form.company.data)
        culture_id = _id(form.culture.data)

        # 1) Перевіряємо на АКТИВНИЙ дубль у цільовій компанії
        q_target = Field.query.filter(func.lower(Field.name) == func.lower(name))
        if hasattr(Field, 'company_id'):
            q_target = q_target.filter(Field.company_id == company_id)

        existing_target_active = q_target.filter(getattr(Field, 'is_active', True) == True).first()
        if existing_target_active:
            flash(f"Поле з назвою '{name}' вже існує!", "danger")
            return render_template('fields/form.html', form=form, title='Нове поле', header='➕ Нове поле')

        # 2) Якщо в цільовій компанії є АРХІВНИЙ — відновлюємо його
        existing_target_arch = q_target.filter(getattr(Field, 'is_active', True) == False).first()
        if existing_target_arch:
            existing_target_arch.is_active = True
            existing_target_arch.cluster_id = cluster_id
            existing_target_arch.culture_id = culture_id
            existing_target_arch.area = form.area.data
            try:
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                flash("Не вдалося відновити поле: порушення унікальності.", "danger")
            except Exception:
                db.session.rollback()
                current_app.logger.exception("Unarchive Field (target) failed")
                flash("Не вдалося відновити поле.", "danger")
            else:
                flash('Архівне поле відновлено.', 'success')
                return redirect(url_for('fields.index'))

            # Якщо ми тут — значить щось пішло не так: повертаємо форму
            return render_template('fields/form.html', form=form, title='Нове поле', header='➕ Нове поле')

        # 3) Пошукаємо БУДЬ-ЯКИЙ архівний запис з такою назвою в інших компаніях
        existing_any_arch = (
            Field.query
            .filter(func.lower(Field.name) == func.lower(name))
            .filter(getattr(Field, 'is_active', True) == False)
            .first()
        )
        if existing_any_arch:
            # Переконаймося, що в цільовій компанії немає активного дубля (ми вже перевірили вище, але лишимо надійність)
            dup_active = (
                Field.query
                .filter(func.lower(Field.name) == func.lower(name))
                .filter(getattr(Field, 'is_active', True) == True)
                .filter(Field.company_id == company_id if hasattr(Field, 'company_id') else True)
                .first()
            )
            if dup_active:
                flash(f"Поле з назвою '{name}' вже існує в обраній компанії.", "danger")
                return render_template('fields/form.html', form=form, title='Нове поле', header='➕ Нове поле')

            # ♻️ Переназначаємо архівний запис на потрібну компанію і відновлюємо
            existing_any_arch.is_active = True
            existing_any_arch.company_id = company_id
            existing_any_arch.cluster_id = cluster_id
            existing_any_arch.culture_id = culture_id
            existing_any_arch.area = form.area.data
            try:
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                flash("Не вдалося відновити поле (переназначення company): унікальність порушена.", "danger")
            except Exception:
                db.session.rollback()
                current_app.logger.exception("Unarchive Field (reassign company) failed")
                flash("Не вдалося відновити поле (переназначення company).", "danger")
            else:
                flash('Архівне поле відновлено і привʼязано до вибраної компанії.', 'success')
                return redirect(url_for('fields.index'))

            return render_template('fields/form.html', form=form, title='Нове поле', header='➕ Нове поле')

        # 4) Взагалі не існує — створюємо нове
        field = Field(
            name=name,
            cluster_id=cluster_id,
            company_id=company_id,
            culture_id=culture_id,
            area=form.area.data
        )
        db.session.add(field)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash("Не вдалося створити поле: порушення унікальності (можливо, активний дублікат).", "danger")
            return render_template('fields/form.html', form=form, title='Нове поле', header='➕ Нове поле')
        except Exception:
            db.session.rollback()
            current_app.logger.exception("Create Field failed")
            flash('Помилка збереження поля.', 'danger')
            return render_template('fields/form.html', form=form, title='Нове поле', header='➕ Нове поле')

        flash('Поле додано!', 'success')
        return redirect(url_for('fields.index'))

    # Якщо POST невалідний — залогуємо, щоб на проді не «мовчало»
    if request.method == 'POST':
        try:
            payload = {
                "name": getattr(form, 'name').data if hasattr(form, 'name') else None,
                "company": _id(getattr(form, 'company').data) if hasattr(form, 'company') else None,
                "cluster": _id(getattr(form, 'cluster').data) if hasattr(form, 'cluster') else None,
                "culture": _id(getattr(form, 'culture').data) if hasattr(form, 'culture') else None,
                "area": getattr(form, 'area').data if hasattr(form, 'area') else None,
            }
        except Exception:
            payload = {}
        current_app.logger.warning("FieldForm POST errors=%s payload=%s", dict(form.errors or {}), payload)

    return render_template('fields/form.html', form=form, title='Нове поле', header='➕ Нове поле')


@fields_bp.route('/fields/<int:id>/edit', methods=['GET', 'POST'])
def edit(id):
    field = Field.query.get_or_404(id)
    form = FieldForm(obj=field)
    if form.validate_on_submit():
        new_name = " ".join((form.name.data or "").split())
        new_company_id = _id(form.company.data)

        # Перевірка дубля ЛИШЕ серед активних у межах компанії
        if field.name.lower() != new_name.lower() or getattr(field, 'company_id', None) != new_company_id:
            q = Field.query.filter(func.lower(Field.name) == func.lower(new_name))
            if hasattr(Field, 'company_id'):
                q = q.filter(Field.company_id == new_company_id)
            q = q.filter(getattr(Field, 'is_active', True) == True)
            existing_active = q.first()
            if existing_active and existing_active.id != field.id:
                flash(f"Поле з назвою '{new_name}' вже існує в обраній компанії.", "danger")
                return render_template('fields/form.html', form=form, title='Редагувати поле', header='✏️ Редагувати поле')

        field.name = new_name
        field.cluster_id = _id(form.cluster.data)
        field.company_id = new_company_id
        field.culture_id = _id(form.culture.data)
        field.area = form.area.data

        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash("Не вдалося зберегти зміни: порушення унікальності (активний дублікат).", "danger")
            return render_template('fields/form.html', form=form, title='Редагувати поле', header='✏️ Редагувати поле')
        except Exception:
            db.session.rollback()
            current_app.logger.exception("Update Field failed")
            flash('Помилка збереження змін.', 'danger')
            return render_template('fields/form.html', form=form, title='Редагувати поле', header='✏️ Редагувати поле')

        flash('Поле оновлено!', 'success')
        return redirect(url_for('fields.index'))

    return render_template('fields/form.html', form=form, title='Редагувати поле', header='✏️ Редагувати поле')


@fields_bp.route('/fields/<int:id>/delete', methods=['POST'])
def delete(id):
    field = Field.query.get_or_404(id)
    try:
        db.session.delete(field)
        db.session.commit()
        flash('Поле видалено!', 'info')
    except IntegrityError:
        # Якщо FK заважає — мʼяке видалення (архів)
        db.session.rollback()
        if hasattr(field, 'is_active'):
            field.is_active = False
            try:
                db.session.commit()
                flash('Поле має залежності — переміщено в архів.', 'warning')
            except Exception:
                db.session.rollback()
                current_app.logger.exception("Archive Field on delete failed")
                flash('Не вдалося видалити/заархівувати поле через залежності.', 'danger')
        else:
            flash('Не вдалося видалити поле через залежності.', 'danger')
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Delete Field failed")
        flash('Сталася помилка при видаленні.', 'danger')
    return redirect(url_for('fields.index'))


# ===================== «ЯДЕРНА КНОПКА» — ПОВНЕ ОЧИЩЕННЯ =====================

@fields_bp.post('/fields/wipe')
def wipe_fields():
    """
    Повне очищення довідника «Поля».
    Параметри (form):
      confirm = "DELETE FIELDS"  (обов'язково)
      force   = "1"              (необов'язково) — видалити також плани/затверджені; у розподілах зняти field_id.
    """
    confirm = (request.form.get('confirm') or '').strip()
    force = request.form.get('force') == '1'

    if confirm != "DELETE FIELDS":
        flash('Введіть точну фразу підтвердження: DELETE FIELDS', 'warning')
        return redirect(url_for('fields.index'))

    # Зберемо всі id полів
    field_ids = [fid for (fid,) in db.session.query(Field.id).all()]
    if not field_ids:
        flash('Немає що очищати — таблиця «Поля» порожня.', 'info')
        return redirect(url_for('fields.index'))

    # Підрахунок залежностей (якщо моделі доступні)
    def _count(model, col_name='field_id'):
        if model is None:
            return 0
        col = getattr(model, col_name)
        return db.session.query(func.count()).select_from(model).filter(col.in_(field_ids)).scalar()

    plans_cnt = _count(Plan)
    appr_cnt = _count(ApprovedPlan)
    alloc_cnt = _count(PayerAllocation)

    if (plans_cnt or appr_cnt) and not force:
        flash(
            f"Залежності знайдені: плани={plans_cnt}, затверджені={appr_cnt}. "
            f"Очистку зупинено. Увімкніть «форс», якщо потрібно стерти повністю.",
            'warning'
        )
        return redirect(url_for('fields.index'))

    try:
        # 1) Відв'язати розподіли (field_id -> NULL), щоб FK не блокував
        if PayerAllocation and alloc_cnt:
            db.session.query(PayerAllocation)\
                .filter(PayerAllocation.field_id.in_(field_ids))\
                .update({PayerAllocation.field_id: None}, synchronize_session=False)

        # 2) Якщо форс — видалити пов'язані плани/затверджені
        if force:
            if ApprovedPlan and appr_cnt:
                db.session.query(ApprovedPlan)\
                    .filter(ApprovedPlan.field_id.in_(field_ids))\
                    .delete(synchronize_session=False)
            if Plan and plans_cnt:
                db.session.query(Plan)\
                    .filter(Plan.field_id.in_(field_ids))\
                    .delete(synchronize_session=False)

        # 3) Видалити всі поля
        deleted = db.session.query(Field).delete(synchronize_session=False)
        db.session.commit()

        notes = []
        if alloc_cnt:
            notes.append(f"відвʼязано розподілів: {alloc_cnt}")
        if force and (plans_cnt or appr_cnt):
            notes.append(f"видалено плани: {plans_cnt}, затверджені: {appr_cnt}")
        tail = f" ({', '.join(notes)})" if notes else ""

        flash(f'Довідник «Поля» очищено. Видалено записів: {deleted}{tail}.', 'success')

    except IntegrityError:
        db.session.rollback()
        current_app.logger.exception("Wipe fields failed (FK integrity).")
        flash('FK-блокування. Увімкніть «форс» або налаштуйте каскади/SET NULL.', 'danger')
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Wipe fields failed.")
        flash('Сталася помилка під час очищення.', 'danger')

    return redirect(url_for('fields.index'))

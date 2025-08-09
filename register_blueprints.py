def register_blueprints(app):
    from modules.reference.routes import bp as reference_bp
    from modules.reference.units.routes import bp as units_bp
    from modules.reference.categories.routes import bp as categories_bp
    from modules.reference.currencies.routes import bp as currencies_bp
    from modules.reference.manufacturers.routes import bp as manufacturers_bp
    from modules.reference.payers.routes import bp as payers_bp
    from modules.reference.clusters.routes import bp as clusters_bp
    from modules.reference.cultures.routes import bp as cultures_bp
    from modules.reference.groups.routes import bp as groups_bp
    from modules.reference.companies.routes import companies_bp
    from modules.reference.products.routes import products_bp
    from modules.reference.fields.routes import fields_bp
    from modules.structure.routes import structure_bp
    from modules.structure.fields_structure.routes import fields_structure_bp
    from modules.structure.summary_structure.routes import bp as summary_structure_bp
    from modules.plans.routes import plans_bp
    from modules.plans.new_plans.routes import new_plans_bp
    from modules.plans.ready_plans.routes import ready_plans_bp
    from modules.plans.approved_plans import bp as approved_plans_bp
    from modules.reference.treatment_types.routes import treatment_types_bp
    from modules.purchases.routes import purchases_bp
    from modules.purchases.needs.routes import needs_bp

    app.register_blueprint(reference_bp)
    app.register_blueprint(units_bp)
    app.register_blueprint(categories_bp)
    app.register_blueprint(currencies_bp)
    app.register_blueprint(manufacturers_bp)
    app.register_blueprint(payers_bp)
    app.register_blueprint(clusters_bp)
    app.register_blueprint(cultures_bp)
    app.register_blueprint(groups_bp)
    app.register_blueprint(companies_bp)
    app.register_blueprint(products_bp)
    app.register_blueprint(fields_bp)
    app.register_blueprint(structure_bp)
    app.register_blueprint(fields_structure_bp)
    app.register_blueprint(summary_structure_bp)
    app.register_blueprint(plans_bp, url_prefix='/plans')
    app.register_blueprint(new_plans_bp)
    app.register_blueprint(ready_plans_bp)
    app.register_blueprint(treatment_types_bp)
    app.register_blueprint(approved_plans_bp, url_prefix='/approved_plans')

    # Блок "Закупівля"
    app.register_blueprint(purchases_bp)
    app.register_blueprint(needs_bp)

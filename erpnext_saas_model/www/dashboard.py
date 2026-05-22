import frappe

no_cache = 1

def get_context(context):
    import press.www.dashboard as press_dashboard
    return press_dashboard.get_context()

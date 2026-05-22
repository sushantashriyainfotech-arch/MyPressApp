import frappe
import re
import os

no_cache = 1

def get_context(context):
    import press.www.dashboard as press_dashboard
    ctx = press_dashboard.get_context() or {}
    context.update(ctx)

    # Dynamically read current asset filenames from Press's built dashboard.html
    press_html = os.path.join(frappe.get_app_path('press'), 'www', 'dashboard.html')
    with open(press_html, 'r') as f:
        content = f.read()

    js_match = re.search(r'src="(/assets/press/dashboard/assets/index-[^"]+\.js)"', content)
    css_match = re.search(r'href="(/assets/press/dashboard/assets/index-[^"]+\.css)"', content)

    context.dashboard_js = js_match.group(1) if js_match else ''
    context.dashboard_css = css_match.group(1) if css_match else ''

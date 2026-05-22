# Copyright (c) 2020, Frappe Technologies Pvt. Ltd. and Contributors
# For license information, please see license.txt


import frappe 
no_cache = 1
def get_context(context):    
	from press.www.dashboard 
	import get_context as press_get_context    
	return press_get_context()

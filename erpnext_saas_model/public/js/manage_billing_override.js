(function () {
	function getDashboardUrl() {
		const site = window.frappe?.boot?.sitename;
		if (!site) {
			return window.location.origin;
		}

		return `${window.location.origin}/dashboard/sites/${site}`;
	}

	function handleManageBillingClick(event) {
		const target = event.target.closest(".login-to-fc, .upgrade-plan-button");
		console.log("Clicked element:", event.target);
		if (!target) return;

		event.preventDefault();
		event.stopPropagation();
		event.stopImmediatePropagation();

		window.open(getDashboardUrl(), "_blank", "noopener");
	}

	document.addEventListener("click", handleManageBillingClick, true);
})();

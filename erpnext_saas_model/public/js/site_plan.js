(function () {
	function updateFieldVisibility(frm) {
		const seatBased = frm.doc.billing_type === "Seat Based";
		["price_inr", "price_usd", "min_seats", "max_seats", "next_plan"].forEach((fieldname) => {
			frm.toggle_display(fieldname, seatBased);
		});
		frm.toggle_reqd("price_inr", seatBased);
		frm.toggle_reqd("price_usd", seatBased);
	}

	function updateHeadline(frm) {
		if (frm.doc.billing_type !== "Seat Based") return;
		const priceInr = Number(frm.doc.price_inr || 0);
		const priceUsd = Number(frm.doc.price_usd || 0);
		frm.dashboard.set_headline(
			__(
				"Seat billing is active at INR {0} / USD {1} per seat for {2}.",
				[priceInr, priceUsd, frm.doc.plan_title || frm.doc.name]
			)
		);
	}

	frappe.ui.form.on("Site Plan", {
		refresh(frm) {
			updateFieldVisibility(frm);
			updateHeadline(frm);
		},
		billing_type(frm) {
			updateFieldVisibility(frm);
			updateHeadline(frm);
		},
		price_inr(frm) {
			updateHeadline(frm);
		},
		price_usd(frm) {
			updateHeadline(frm);
		},
	});
})();

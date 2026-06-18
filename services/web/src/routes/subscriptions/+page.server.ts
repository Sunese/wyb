import { env } from '$env/dynamic/private';
import { error } from '@sveltejs/kit';
import type { PageServerLoad } from './$types';

export interface Subscription {
	id: string;
	merchant_name: string;
	currency: string;
	cadence_days: number;
	cadence_label: string;
	current_amount_minor: number;
	previous_amount_minor: number | null;
	price_changed: boolean;
	last_charge_date: string;
	next_expected_date: string;
	status: string;
	first_seen_date: string;
	occurrence_count: number;
	annual_estimate_minor: number;
	detected_at: string;
	updated_at: string;
}

function detectUrl() {
	const url = env.services__detect__http__0;
	if (!url) error(500, 'detect service URL not configured');
	return url;
}

export const load: PageServerLoad = async () => {
	const base = detectUrl();
	const res = await fetch(`${base}/subscriptions`).catch(() => null);

	if (!res || !res.ok) {
		return { subscriptions: [] as Subscription[] };
	}

	const subscriptions: Subscription[] = await res.json();
	return { subscriptions };
};

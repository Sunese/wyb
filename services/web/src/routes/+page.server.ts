import { env } from '$env/dynamic/private';
import { error } from '@sveltejs/kit';
import type { PageServerLoad, Actions } from './$types';

export interface Transaction {
	id: string;
	date: string;
	amountMinor: number;
	currency: string;
	rawDescription: string;
	accountId: string | null;
	category: string;
	merchantName: string | null;
	categoryOverridden: boolean;
}

function ledgerUrl() {
	const url = env.services__ledger__http__0;
	if (!url) error(500, 'ledger service URL not configured');
	return url;
}

export const load: PageServerLoad = async ({ url }) => {
	const limit = url.searchParams.get('limit') ?? '100';
	const offset = url.searchParams.get('offset') ?? '0';

	const res = await fetch(`${ledgerUrl()}/transactions?limit=${limit}&offset=${offset}`);
	if (!res.ok) error(res.status, 'failed to fetch transactions from ledger');

	const transactions: Transaction[] = await res.json();
	return { transactions };
};

export const actions: Actions = {
	setCategory: async ({ request }) => {
		const data = await request.formData();
		const id = data.get('id') as string;
		const category = data.get('category') as string;

		const res = await fetch(`${ledgerUrl()}/transactions/${id}/category`, {
			method: 'PATCH',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ category }),
		});

		if (!res.ok) error(res.status, 'failed to update category');
	},
};

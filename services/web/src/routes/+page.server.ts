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

export interface AccountImportStatus {
	accountId: string | null;
	lastImportAt: string | null;
	coverageEnd: string | null;
	daysSinceLastImport: number | null;
	transactionCount: number;
}

export interface ImportStatus {
	lastImportAt: string | null;
	coverageEnd: string | null;
	daysSinceLastImport: number | null;
	transactionCount: number;
	accounts: AccountImportStatus[];
}

function ledgerUrl() {
	const url = env.services__ledger__http__0;
	if (!url) error(500, 'ledger service URL not configured');
	return url;
}

export const load: PageServerLoad = async ({ url }) => {
	const limit = url.searchParams.get('limit') ?? '100';
	const offset = url.searchParams.get('offset') ?? '0';
	const base = ledgerUrl();

	const [txRes, catRes, importRes] = await Promise.all([
		fetch(`${base}/transactions?limit=${limit}&offset=${offset}`),
		fetch(`${base}/categories`),
		// Import status drives an optional nudge — never let it break the page.
		fetch(`${base}/imports/status`).catch(() => null)
	]);
	if (!txRes.ok) error(txRes.status, 'failed to fetch transactions from ledger');
	if (!catRes.ok) error(catRes.status, 'failed to fetch categories from ledger');

	const transactions: Transaction[] = await txRes.json();
	const categories: string[] = await catRes.json();
	const importStatus: ImportStatus | null =
		importRes && importRes.ok ? await importRes.json() : null;
	return { transactions, categories, importStatus };
};

export const actions: Actions = {
	setCategory: async ({ request }) => {
		const data = await request.formData();
		const id = data.get('id') as string;
		const category = data.get('category') as string;

		const res = await fetch(`${ledgerUrl()}/transactions/${id}/category`, {
			method: 'PATCH',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ category })
		});

		if (!res.ok) error(res.status, 'failed to update category');
	}
};

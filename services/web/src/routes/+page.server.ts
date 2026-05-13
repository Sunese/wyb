import { env } from '$env/dynamic/private';
import { error } from '@sveltejs/kit';
import type { PageServerLoad } from './$types';

interface Transaction {
	id: string;
	date: string;
	amountMinor: number;
	currency: string;
	rawDescription: string;
	accountId: string;
}

export const load: PageServerLoad = async ({ url }) => {
	const ledgerUrl = env.services__ledger__http__0;
	if (!ledgerUrl) {
		error(500, 'ledger service URL not configured');
	}

	const limit = url.searchParams.get('limit') ?? '100';
	const offset = url.searchParams.get('offset') ?? '0';

	const res = await fetch(`${ledgerUrl}/transactions?limit=${limit}&offset=${offset}`);
	if (!res.ok) {
		error(res.status, 'failed to fetch transactions from ledger');
	}

	const transactions: Transaction[] = await res.json();
	return { transactions };
};

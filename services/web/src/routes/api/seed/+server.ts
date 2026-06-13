import { json, type RequestHandler } from '@sveltejs/kit';
import { env } from '$env/dynamic/private';

export const POST: RequestHandler = async () => {
	const ledgerUrl = env.services__ledger__http__0;
	if (!ledgerUrl) {
		return new Response('ledger service URL not found', { status: 500 });
	}

	const response = await fetch(`${ledgerUrl}/transactions/seed`, {
		method: 'POST'
	});

	return json(await response.json());
};

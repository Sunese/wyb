import { env } from '$env/dynamic/private';
import { error, json } from '@sveltejs/kit';
import type { RequestHandler } from './$types';

export const GET: RequestHandler = async ({ params }) => {
	const base = env.services__detect__http__0;
	if (!base) error(500, 'detect service URL not configured');

	const res = await fetch(`${base}/subscriptions/${params.id}/charges`).catch(() => null);
	if (!res || !res.ok) return json([]);

	return json(await res.json());
};

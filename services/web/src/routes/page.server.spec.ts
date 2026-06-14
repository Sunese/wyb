import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('$env/dynamic/private', () => ({
	env: { services__ledger__http__0: 'http://ledger-test' }
}));

const { load } = await import('./+page.server');

const MOCK_TRANSACTIONS = [
	{
		id: 'a1b2c3d4-0000-0000-0000-000000000001',
		date: '2025-01-01',
		amountMinor: -5000,
		currency: 'DKK',
		rawDescription: 'NETTO',
		accountId: 'acc1',
		category: 'Groceries',
		merchantName: null,
		categoryOverridden: false
	}
];

const MOCK_CATEGORIES = ['Uncategorized', 'Groceries', 'Transport', 'Health'];

const MOCK_IMPORT_STATUS = {
	lastImportAt: '2025-05-20T10:00:00Z',
	coverageEnd: '2025-05-19',
	daysSinceLastImport: 12,
	transactionCount: 1,
	accounts: [
		{
			accountId: 'acc1',
			lastImportAt: '2025-05-20T10:00:00Z',
			coverageEnd: '2025-05-19',
			daysSinceLastImport: 12,
			transactionCount: 1
		}
	]
};

function makeUrl(params: Record<string, string> = {}) {
	const u = new URL('http://localhost/');
	for (const [k, v] of Object.entries(params)) u.searchParams.set(k, v);
	return u;
}

beforeEach(() => {
	vi.restoreAllMocks();
});

describe('load', () => {
	function mockFetch(
		categories = MOCK_CATEGORIES,
		transactions = MOCK_TRANSACTIONS,
		importStatus: unknown = MOCK_IMPORT_STATUS
	) {
		return vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
			if (input.toString().includes('/categories')) {
				return new Response(JSON.stringify(categories), { status: 200 });
			}
			if (input.toString().includes('/imports/status')) {
				return new Response(JSON.stringify(importStatus), { status: 200 });
			}
			return new Response(JSON.stringify(transactions), { status: 200 });
		});
	}

	async function runLoad(params: Record<string, string> = {}) {
		const result = await load({ url: makeUrl(params) } as Parameters<typeof load>[0]);
		if (!result) throw new Error('load returned void');
		return result as { transactions: unknown[]; categories: string[]; importStatus: unknown };
	}

	it('returns categories fetched from the ledger API', async () => {
		mockFetch();
		const result = await runLoad();
		expect(result.categories).toEqual(MOCK_CATEGORIES);
	});

	it('categories come from the API, not a hardcoded list', async () => {
		const sentinel = ['__sentinel_category__'];
		mockFetch(sentinel);
		const result = await runLoad();
		expect(result.categories).toEqual(sentinel);
	});

	it('calls GET /categories on the ledger base URL', async () => {
		const fetchSpy = mockFetch();
		await runLoad();
		const urls = fetchSpy.mock.calls.map((c) => c[0].toString());
		expect(urls).toContain('http://ledger-test/categories');
	});

	it('returns transactions alongside categories', async () => {
		mockFetch();
		const result = await runLoad();
		expect(result.transactions).toEqual(MOCK_TRANSACTIONS);
		expect(result.categories).toEqual(MOCK_CATEGORIES);
	});

	it('returns import status fetched from the ledger API', async () => {
		const fetchSpy = mockFetch();
		const result = await runLoad();
		expect(result.importStatus).toEqual(MOCK_IMPORT_STATUS);
		const urls = fetchSpy.mock.calls.map((c) => c[0].toString());
		expect(urls).toContain('http://ledger-test/imports/status');
	});

	it('import status is null (not fatal) when the ledger endpoint errors', async () => {
		vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
			if (input.toString().includes('/categories')) {
				return new Response(JSON.stringify(MOCK_CATEGORIES), { status: 200 });
			}
			if (input.toString().includes('/imports/status')) {
				return new Response('error', { status: 500 });
			}
			return new Response(JSON.stringify(MOCK_TRANSACTIONS), { status: 200 });
		});
		const result = await runLoad();
		expect(result.importStatus).toBeNull();
		expect(result.transactions).toEqual(MOCK_TRANSACTIONS);
	});
});

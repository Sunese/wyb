<script lang="ts">
	import type { PageData } from './$types';

	let { data }: { data: PageData } = $props();

	const fmt = new Intl.NumberFormat('da-DK', {
		style: 'currency',
		currency: 'DKK',
		minimumFractionDigits: 2,
	});

	function formatAmount(amountMinor: number, currency: string): string {
		return fmt.format(amountMinor / 100);
	}

	function formatDate(iso: string): string {
		return new Date(iso).toLocaleDateString('da-DK', {
			timeZone: 'Europe/Copenhagen',
			year: 'numeric',
			month: '2-digit',
			day: '2-digit',
		});
	}
</script>

<main class="mx-auto max-w-5xl p-6">
	<h1 class="mb-6 text-2xl font-semibold">Transactions</h1>

	{#if data.transactions.length === 0}
		<p class="text-gray-500">No transactions found.</p>
	{:else}
		<table class="w-full border-collapse text-sm">
			<thead>
				<tr class="border-b border-gray-200 text-left text-gray-500">
					<th class="pb-2 pr-6 font-medium">Date</th>
					<th class="pb-2 pr-6 font-medium">Description</th>
					<th class="pb-2 pr-6 font-medium">Account</th>
					<th class="pb-2 text-right font-medium">Amount</th>
				</tr>
			</thead>
			<tbody>
				{#each data.transactions as tx (tx.id)}
					<tr class="border-b border-gray-100 hover:bg-gray-50">
						<td class="py-2 pr-6 tabular-nums text-gray-500">{formatDate(tx.date)}</td>
						<td class="py-2 pr-6">{tx.rawDescription}</td>
						<td class="py-2 pr-6 text-gray-400">{tx.accountId}</td>
						<td
							class="py-2 text-right tabular-nums {tx.amountMinor < 0
								? 'text-red-600'
								: 'text-green-700'}"
						>
							{formatAmount(tx.amountMinor, tx.currency)}
						</td>
					</tr>
				{/each}
			</tbody>
		</table>
		<p class="mt-4 text-xs text-gray-400">Showing {data.transactions.length} transactions</p>
	{/if}
</main>

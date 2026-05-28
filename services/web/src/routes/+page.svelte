<script lang="ts">
	import { enhance } from '$app/forms';
	import type { PageData } from './$types';

	let { data }: { data: PageData } = $props();

	const CATEGORY_COLORS: Record<string, string> = {
		Income: 'bg-green-100 text-green-800',
		Groceries: 'bg-lime-100 text-lime-800',
		Dining: 'bg-orange-100 text-orange-800',
		Transport: 'bg-blue-100 text-blue-800',
		Shopping: 'bg-purple-100 text-purple-800',
		Entertainment: 'bg-pink-100 text-pink-800',
		Utilities: 'bg-cyan-100 text-cyan-800',
		Housing: 'bg-stone-100 text-stone-800',
		Health: 'bg-red-100 text-red-800',
		Home: 'bg-rose-100 text-rose-800',
		Auto: 'bg-sky-100 text-sky-800',
		Travel: 'bg-violet-100 text-violet-800',
		Subscriptions: 'bg-indigo-100 text-indigo-800',
		Transfer: 'bg-gray-100 text-gray-700',
		Investment: 'bg-emerald-100 text-emerald-800',
		ATM: 'bg-yellow-100 text-yellow-800',
		Beer: 'bg-amber-100 text-amber-800',
		Expense: 'bg-gray-100 text-gray-700',
		Uncategorized: 'bg-gray-50 text-gray-400 dark:bg-gray-800 dark:text-gray-500'
	};

	let editingId = $state<string | null>(null);

	const fmt = new Intl.NumberFormat('da-DK', {
		style: 'currency',
		currency: 'DKK',
		minimumFractionDigits: 2
	});

	function formatAmount(amountMinor: number): string {
		return fmt.format(amountMinor / 100);
	}

	function formatDate(iso: string): string {
		return new Date(iso).toLocaleDateString('da-DK', {
			timeZone: 'Europe/Copenhagen',
			year: 'numeric',
			month: '2-digit',
			day: '2-digit'
		});
	}

	function categoryColor(category: string): string {
		return CATEGORY_COLORS[category] ?? 'bg-gray-100 text-gray-600';
	}
</script>

<main class="mx-auto max-w-6xl p-6">
	<h1 class="mb-6 text-2xl font-semibold">Transactions</h1>

	{#if data.transactions.length === 0}
		<p class="text-gray-500 dark:text-gray-400">No transactions found.</p>
	{:else}
		<table class="w-full border-collapse text-sm">
			<thead>
				<tr
					class="border-b border-gray-200 text-left text-gray-500 dark:border-gray-700 dark:text-gray-400"
				>
					<th class="pb-2 pr-4 font-medium">Date</th>
					<th class="pb-2 pr-4 font-medium">Merchant / Description</th>
					<th class="pb-2 pr-4 font-medium">Category</th>
					<th class="pb-2 pr-4 font-medium">Account / Source</th>
					<th class="pb-2 text-right font-medium">Amount</th>
				</tr>
			</thead>
			<tbody>
				{#each data.transactions as tx (tx.id)}
					<tr
						class="border-b border-gray-100 hover:bg-gray-50 dark:border-gray-800 dark:hover:bg-gray-900"
					>
						<td class="py-2 pr-4 tabular-nums text-gray-500 dark:text-gray-400"
							>{formatDate(tx.date)}</td
						>
						<td class="py-2 pr-4">
							{#if tx.merchantName}
								<span class="font-medium">{tx.merchantName}</span>
								<span class="ml-1 text-xs text-gray-400 dark:text-gray-500"
									>{tx.rawDescription}</span
								>
							{:else}
								{tx.rawDescription}
							{/if}
						</td>
						<td class="py-2 pr-4">
							{#if editingId === tx.id}
								<form
									method="POST"
									action="?/setCategory"
									use:enhance={() => {
										return ({ update }) => {
											editingId = null;
											update({ invalidateAll: true });
										};
									}}
								>
									<input type="hidden" name="id" value={tx.id} />
									<select
										name="category"
										class="rounded border border-gray-300 text-xs dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100"
										onchange={(e) => (e.currentTarget.form as HTMLFormElement)?.requestSubmit()}
										onblur={() => (editingId = null)}
									>
										{#each data.categories as cat (cat)}
											<option value={cat} selected={cat === tx.category}>{cat}</option>
										{/each}
									</select>
								</form>
							{:else}
								<button
									type="button"
									onclick={() => (editingId = tx.id)}
									class="rounded px-1.5 py-0.5 text-xs font-medium {categoryColor(
										tx.category
									)} {tx.categoryOverridden ? 'ring-1 ring-inset ring-current/30' : ''}"
									title={tx.categoryOverridden
										? 'Manually overridden — click to change'
										: 'Click to override'}
								>
									{tx.category}
								</button>
							{/if}
						</td>
						<td class="py-2 pr-4 text-xs text-gray-400 dark:text-gray-500">{tx.accountId ?? '—'}</td
						>
						<td
							class="py-2 text-right tabular-nums {tx.amountMinor < 0
								? 'text-red-600 dark:text-red-400'
								: 'text-green-700 dark:text-green-400'}"
						>
							{formatAmount(tx.amountMinor)}
						</td>
					</tr>
				{/each}
			</tbody>
		</table>
		<p class="mt-4 text-xs text-gray-400 dark:text-gray-500">
			Showing {data.transactions.length} transactions
		</p>
	{/if}
</main>

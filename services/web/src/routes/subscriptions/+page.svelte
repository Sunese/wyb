<script lang="ts">
	import type { PageData } from './$types';

	let { data }: { data: PageData } = $props();

	const fmt = new Intl.NumberFormat('da-DK', {
		style: 'currency',
		currency: 'DKK',
		minimumFractionDigits: 2
	});

	function formatAmount(amountMinor: number): string {
		return fmt.format(Math.abs(amountMinor) / 100);
	}

	function formatDate(iso: string): string {
		return new Date(iso).toLocaleDateString('da-DK', {
			timeZone: 'Europe/Copenhagen',
			year: 'numeric',
			month: '2-digit',
			day: '2-digit'
		});
	}

	function statusBadge(status: string): string {
		if (status === 'active')
			return 'bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-300';
		if (status === 'missed') return 'bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300';
		return 'bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300';
	}

	function cadenceLabel(label: string): string {
		return label.charAt(0).toUpperCase() + label.slice(1);
	}
</script>

<main class="mx-auto max-w-4xl p-6">
	<h1 class="mb-6 text-2xl font-semibold">Subscriptions</h1>

	{#if data.subscriptions.length === 0}
		<p class="text-gray-500 dark:text-gray-400">No subscriptions detected yet.</p>
	{:else}
		<table class="w-full border-collapse text-sm">
			<thead>
				<tr
					class="border-b border-gray-200 text-left text-gray-500 dark:border-gray-700 dark:text-gray-400"
				>
					<th class="pb-2 pr-4 font-medium">Merchant</th>
					<th class="pb-2 pr-4 font-medium">Cadence</th>
					<th class="pb-2 pr-4 font-medium">Amount</th>
					<th class="pb-2 pr-4 font-medium">Annual total</th>
					<th class="pb-2 pr-4 font-medium">Next charge</th>
					<th class="pb-2 pr-4 font-medium">Status</th>
				</tr>
			</thead>
			<tbody>
				{#each data.subscriptions as sub (sub.id)}
					<tr
						class="border-b border-gray-100 hover:bg-gray-50 dark:border-gray-800 dark:hover:bg-gray-900"
					>
						<td class="py-3 pr-4 font-medium">
							{sub.merchant_name}
							{#if sub.price_changed}
								<span
									title="Price changed from {formatAmount(sub.previous_amount_minor ?? 0)}"
									class="ml-1.5 rounded bg-orange-100 px-1 py-0.5 text-xs text-orange-700 dark:bg-orange-900/40 dark:text-orange-300"
								>
									price ↑
								</span>
							{/if}
						</td>
						<td class="py-3 pr-4 text-gray-600 dark:text-gray-300">
							{cadenceLabel(sub.cadence_label)}
						</td>
						<td class="py-3 pr-4 tabular-nums">
							{formatAmount(sub.current_amount_minor)}
							{#if sub.price_changed && sub.previous_amount_minor != null}
								<span class="ml-1 text-xs text-gray-400 line-through dark:text-gray-500">
									{formatAmount(sub.previous_amount_minor)}
								</span>
							{/if}
						</td>
						<td class="py-3 pr-4 tabular-nums text-gray-600 dark:text-gray-300">
							{formatAmount(sub.annual_estimate_minor)}
						</td>
						<td class="py-3 pr-4 tabular-nums text-gray-500 dark:text-gray-400">
							{formatDate(sub.next_expected_date)}
						</td>
						<td class="py-3">
							<span class="rounded px-1.5 py-0.5 text-xs font-medium {statusBadge(sub.status)}">
								{sub.status}
							</span>
						</td>
					</tr>
				{/each}
			</tbody>
		</table>
		<p class="mt-4 text-xs text-gray-400 dark:text-gray-500">
			{data.subscriptions.length} subscription{data.subscriptions.length === 1 ? '' : 's'} · annual total
			{formatAmount(data.subscriptions.reduce((sum, s) => sum + s.annual_estimate_minor, 0))}
		</p>
	{/if}
</main>

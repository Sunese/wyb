<script lang="ts">
	import type { PageData } from './$types';

	let { data }: { data: PageData } = $props();

	interface MerchantCharge {
		id: string;
		transaction_id: string;
		merchant_name: string;
		currency: string;
		amount_minor: number;
		charge_date: string;
	}

	let expandedId = $state<string | null>(null);
	let chargesCache = $state<Record<string, MerchantCharge[]>>({});
	let loadingId = $state<string | null>(null);

	async function toggleCharges(subId: string) {
		if (expandedId === subId) {
			expandedId = null;
			return;
		}
		expandedId = subId;
		if (chargesCache[subId]) return;

		loadingId = subId;
		try {
			const res = await fetch(`/api/subscriptions/${subId}/charges`);
			chargesCache[subId] = res.ok ? await res.json() : [];
		} catch {
			chargesCache[subId] = [];
		} finally {
			loadingId = null;
		}
	}

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
					<th class="pb-2 pr-4 font-medium"></th>
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
						class="cursor-pointer border-b border-gray-100 hover:bg-gray-50 dark:border-gray-800 dark:hover:bg-gray-900"
						onclick={() => toggleCharges(sub.id)}
					>
						<td class="py-3 pr-2 text-gray-400 dark:text-gray-500">
							{#if loadingId === sub.id}
								<span
									class="inline-block h-3 w-3 animate-spin rounded-full border border-current border-t-transparent"
								></span>
							{:else}
								<span class="text-xs">{expandedId === sub.id ? '▾' : '▸'}</span>
							{/if}
						</td>
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
					{#if expandedId === sub.id}
						<tr class="border-b border-gray-100 dark:border-gray-800">
							<td colspan="7" class="bg-gray-50 px-4 pb-3 pt-1 dark:bg-gray-900/50">
								{#if !chargesCache[sub.id]}
									<p class="py-2 text-xs text-gray-400">Loading…</p>
								{:else if chargesCache[sub.id].length === 0}
									<p class="py-2 text-xs text-gray-400">No charge history found.</p>
								{:else}
									<table class="w-full text-xs">
										<thead>
											<tr class="text-gray-400 dark:text-gray-500">
												<th class="pb-1 pr-4 text-left font-medium">Date</th>
												<th class="pb-1 pr-4 text-right font-medium">Amount</th>
											</tr>
										</thead>
										<tbody>
											{#each chargesCache[sub.id] as charge (charge.id)}
												<tr class="text-gray-600 dark:text-gray-300">
													<td class="py-0.5 pr-4">{formatDate(charge.charge_date)}</td>
													<td class="py-0.5 pr-4 text-right tabular-nums"
														>{formatAmount(charge.amount_minor)}</td
													>
												</tr>
											{/each}
										</tbody>
									</table>
								{/if}
							</td>
						</tr>
					{/if}
				{/each}
			</tbody>
		</table>
		<p class="mt-4 text-xs text-gray-400 dark:text-gray-500">
			{data.subscriptions.length} subscription{data.subscriptions.length === 1 ? '' : 's'} · annual total
			{formatAmount(data.subscriptions.reduce((sum, s) => sum + s.annual_estimate_minor, 0))}
		</p>
	{/if}
</main>

package main

import (
	"strings"
	"testing"
	"time"
)

func mustParseDate(s string) time.Time {
	t, err := time.Parse("2006-01-02", s)
	if err != nil {
		panic(err)
	}
	return t
}

// ── decodeToUTF8 ─────────────────────────────────────────────────────────────

func TestDecodeToUTF8_PlainUTF8(t *testing.T) {
	input := []byte("Dato;Tekst;Beløb\n")
	got, err := decodeToUTF8(input)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if string(got) != string(input) {
		t.Errorf("plain UTF-8 should be returned unchanged")
	}
}

func TestDecodeToUTF8_BOMStripped(t *testing.T) {
	bom := []byte{0xEF, 0xBB, 0xBF}
	payload := []byte("Dato;Tekst;Beløb\n")
	got, err := decodeToUTF8(append(bom, payload...))
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if string(got) != string(payload) {
		t.Errorf("BOM should be stripped; got %q", got)
	}
}

func TestDecodeToUTF8_Windows1252(t *testing.T) {
	// "Beløb" in Windows-1252: ø = 0xF8
	input := []byte("Dato;Tekst;Bel\xf8b\n")
	got, err := decodeToUTF8(input)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	want := "Dato;Tekst;Beløb\n"
	if string(got) != want {
		t.Errorf("Windows-1252: got %q, want %q", got, want)
	}
}

// ── sniffHeader ───────────────────────────────────────────────────────────────

func TestSniffHeader_Semicolon(t *testing.T) {
	data := []byte("Dato;Tekst;Beløb\n01.01.2026;Test;-100,00\n")
	header, err := sniffHeader(data)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(header) != 3 || header[0] != "Dato" {
		t.Errorf("semicolon: got %v", header)
	}
}

func TestSniffHeader_Comma(t *testing.T) {
	data := []byte("Date,Description,Amount\n2026-01-01,Test,-100\n")
	header, err := sniffHeader(data)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(header) != 3 || header[0] != "Date" {
		t.Errorf("comma: got %v", header)
	}
}

func TestSniffHeader_Tab(t *testing.T) {
	data := []byte("Date\tDescription\tAmount\n2026-01-01\tTest\t-100\n")
	header, err := sniffHeader(data)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(header) != 3 || header[0] != "Date" {
		t.Errorf("tab: got %v", header)
	}
}

func TestSniffHeader_UnknownFormat(t *testing.T) {
	data := []byte("onlyone\nsecondrow\n")
	_, err := sniffHeader(data)
	if err == nil {
		t.Error("expected error for single-column data")
	}
}

// ── danskeDesktopParser ───────────────────────────────────────────────────────

func TestDanskeDesktopParser_DetectHeader(t *testing.T) {
	p := &danskeDesktopParser{}

	ok := [][]string{
		{"Dato", "Tekst", "Beløb", "Saldo", "Status", "Afstemt"},
		// ø replaced with replacement char (some exporters do this)
		{"Dato", "Tekst", "Bel�b", "Saldo", "Status", "Afstemt"},
	}
	for _, h := range ok {
		if !p.DetectHeader(h) {
			t.Errorf("desktop: should match %v", h)
		}
	}

	notOk := [][]string{
		// iOS header — must NOT match desktop
		{"Dato", "Kategori", "Underkategori", "Tekst", "Beløb", "Saldo", "Status", "Afstemt"},
		{"Date", "Text", "Amount"},
		{"Dato", "Tekst"},
	}
	for _, h := range notOk {
		if p.DetectHeader(h) {
			t.Errorf("desktop: should NOT match %v", h)
		}
	}
}

func TestDanskeDesktopParser_Parse(t *testing.T) {
	csv := `"Dato";"Tekst";"Beløb";"Saldo";"Status";"Afstemt"
"15.06.2026";"Netflix";"149,00";"4.816,19";"Udført";"Nej"
"01.06.2026";"MobilePay Rikke";"-3.500,00";"1.316,19";"Udført";"Nej"
`
	p := &danskeDesktopParser{}
	rows, err := p.Parse(strings.NewReader(csv), "test.csv", "checking")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(rows) != 2 {
		t.Fatalf("want 2 rows, got %d", len(rows))
	}

	r0 := rows[0]
	if r0.Description != "Netflix" {
		t.Errorf("description: got %q", r0.Description)
	}
	if r0.AmountMinor != 14900 {
		t.Errorf("amount: got %d, want 14900", r0.AmountMinor)
	}
	if !r0.Date.Equal(mustParseDate("2026-06-15")) {
		t.Errorf("date: got %v", r0.Date)
	}
	if r0.Currency != "DKK" {
		t.Errorf("currency: got %q", r0.Currency)
	}
	if r0.AccountID != "checking" {
		t.Errorf("accountID: got %q", r0.AccountID)
	}

	r1 := rows[1]
	if r1.AmountMinor != -350000 {
		t.Errorf("negative amount: got %d, want -350000", r1.AmountMinor)
	}
}

// ── danskeIosParser ───────────────────────────────────────────────────────────

func TestDanskeIosParser_DetectHeader(t *testing.T) {
	p := &danskeIosParser{}

	ok := [][]string{
		{"Dato", "Kategori", "Underkategori", "Tekst", "Beløb", "Saldo", "Status", "Afstemt"},
		{"Dato", "Kategori", "Underkategori", "Tekst", "Bel�b", "Saldo", "Status", "Afstemt"},
	}
	for _, h := range ok {
		if !p.DetectHeader(h) {
			t.Errorf("ios: should match %v", h)
		}
	}

	notOk := [][]string{
		// Desktop header — must NOT match iOS
		{"Dato", "Tekst", "Beløb", "Saldo", "Status", "Afstemt"},
		{"Dato", "Kategori", "Underkategori", "Tekst"}, // too short
		{"Date", "Category", "SubCategory", "Text", "Amount"},
	}
	for _, h := range notOk {
		if p.DetectHeader(h) {
			t.Errorf("ios: should NOT match %v", h)
		}
	}
}

func TestDanskeIosParser_Parse(t *testing.T) {
	// Unquoted, two extra columns before Tekst.
	csv := `Dato;Kategori;Underkategori;Tekst;Beløb;Saldo;Status;Afstemt
18.06.2026;;;Netflix.Com;-149,00;;Venter;Nej
15.06.2026;Ukategoriseret;Ukategoriseret;MobilePay Podimo ApS;-129,00;13.665,48;Udført;Nej
02.06.2026;Øvrige udgifter;Telefon;Norlys.dk;-339,00;15.697,28;Udført;Nej
`
	p := &danskeIosParser{}
	rows, err := p.Parse(strings.NewReader(csv), "4662952419.csv", "4662952419")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(rows) != 3 {
		t.Fatalf("want 3 rows, got %d", len(rows))
	}

	r0 := rows[0]
	if r0.Description != "Netflix.Com" {
		t.Errorf("description: got %q", r0.Description)
	}
	if r0.AmountMinor != -14900 {
		t.Errorf("amount: got %d, want -14900", r0.AmountMinor)
	}
	if !r0.Date.Equal(mustParseDate("2026-06-18")) {
		t.Errorf("date: got %v", r0.Date)
	}
	if r0.Currency != "DKK" {
		t.Errorf("currency: got %q", r0.Currency)
	}
	if r0.AccountID != "4662952419" {
		t.Errorf("accountID: got %q", r0.AccountID)
	}

	// Row with empty Kategori/Underkategori (pending transaction)
	if rows[0].Description != "Netflix.Com" {
		t.Errorf("pending row description wrong")
	}

	// Row with real categories — description should still come from Tekst col
	if rows[2].Description != "Norlys.dk" {
		t.Errorf("categorised row description: got %q", rows[2].Description)
	}
	if rows[2].AmountMinor != -33900 {
		t.Errorf("categorised row amount: got %d, want -33900", rows[2].AmountMinor)
	}
}

// ── registry / detectParser ───────────────────────────────────────────────────

func TestDetectParser_DesktopHeader(t *testing.T) {
	header := []string{"Dato", "Tekst", "Beløb", "Saldo", "Status", "Afstemt"}
	p := detectParser(header)
	if p == nil {
		t.Fatal("expected a parser, got nil")
	}
	if p.BankName() != "danskebank-desktop" {
		t.Errorf("want danskebank-desktop, got %q", p.BankName())
	}
}

func TestDetectParser_IosHeader(t *testing.T) {
	header := []string{"Dato", "Kategori", "Underkategori", "Tekst", "Beløb", "Saldo", "Status", "Afstemt"}
	p := detectParser(header)
	if p == nil {
		t.Fatal("expected a parser, got nil")
	}
	if p.BankName() != "danskebank-ios" {
		t.Errorf("want danskebank-ios, got %q", p.BankName())
	}
}

func TestDetectParser_UnknownHeader(t *testing.T) {
	header := []string{"Date", "Description", "Amount"}
	if p := detectParser(header); p != nil {
		t.Errorf("expected nil, got %q", p.BankName())
	}
}

// ── ComputeDedupKey ───────────────────────────────────────────────────────────

func TestComputeDedupKey_Deterministic(t *testing.T) {
	row := Row{
		AccountID:   "salary",
		Date:        mustParseDate("2026-01-15"),
		AmountMinor: 350000,
		Currency:    "DKK",
		Description: "NETS BETALING",
	}
	a := ComputeDedupKey(row)
	b := ComputeDedupKey(row)
	if a != b {
		t.Errorf("dedup key not deterministic: %q vs %q", a, b)
	}
	if a == "" {
		t.Error("dedup key should not be empty")
	}
}

func TestComputeDedupKey_DiffersAcrossFields(t *testing.T) {
	base := Row{
		AccountID:   "salary",
		Date:        mustParseDate("2026-01-15"),
		AmountMinor: 350000,
		Currency:    "DKK",
		Description: "NETS BETALING",
	}
	cases := []struct {
		name string
		row  Row
	}{
		{"different account", func() Row { r := base; r.AccountID = "savings"; return r }()},
		{"different date", func() Row { r := base; r.Date = mustParseDate("2026-01-16"); return r }()},
		{"different amount", func() Row { r := base; r.AmountMinor = 1; return r }()},
		{"different currency", func() Row { r := base; r.Currency = "EUR"; return r }()},
		{"different description", func() Row { r := base; r.Description = "OTHER"; return r }()},
	}
	baseKey := ComputeDedupKey(base)
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			if got := ComputeDedupKey(c.row); got == baseKey {
				t.Errorf("key collision: %q", got)
			}
		})
	}
}

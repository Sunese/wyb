package main

import (
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
	// Single-column lines can't be disambiguated.
	data := []byte("onlyone\nsecondrow\n")
	_, err := sniffHeader(data)
	if err == nil {
		t.Error("expected error for single-column data")
	}
}

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

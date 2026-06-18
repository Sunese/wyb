package main

import (
	"testing"
	"time"
)

func TestParseDanishAmount(t *testing.T) {
	cases := []struct {
		input string
		want  int64
	}{
		{"-3.842,00", -384200},
		{"22.000,00", 2200000},
		{"-88,00", -8800},
		{"68,00", 6800},
		{"-146,37", -14637},
		{"0,00", 0},
	}

	for _, c := range cases {
		t.Run(c.input, func(t *testing.T) {
			got, err := parseDanishAmount(c.input)
			if err != nil {
				t.Fatalf("unexpected error: %v", err)
			}
			if got != c.want {
				t.Errorf("parseDanishAmount(%q) = %d, want %d", c.input, got, c.want)
			}
		})
	}
}

func TestParseDanskeBank_Desktop(t *testing.T) {
	rows, err := ParseFile("../../testdata/danskebank_salary_20250101_20251231.csv")
	if err != nil {
		t.Fatalf("ParseFile: %v", err)
	}
	if len(rows) == 0 {
		t.Fatal("expected at least one row")
	}

	r := rows[0]
	if r.AccountID != "danskebank_salary_20250101_20251231" {
		t.Errorf("AccountID = %q, want %q", r.AccountID, "danskebank_salary_20250101_20251231")
	}
	if r.Currency != "DKK" {
		t.Errorf("Currency = %q, want DKK", r.Currency)
	}
	wantDate := time.Date(2026, 5, 4, 0, 0, 0, 0, time.UTC)
	if !r.Date.Equal(wantDate) {
		t.Errorf("first row Date = %v, want %v", r.Date, wantDate)
	}
	if r.AmountMinor != 350000 {
		t.Errorf("AmountMinor = %d, want 350000", r.AmountMinor)
	}
}

func TestParseDanskeBank_Ios(t *testing.T) {
	rows, err := ParseFile("../../testdata/danskebank_ios_sample.csv")
	if err != nil {
		t.Fatalf("ParseFile: %v", err)
	}
	if len(rows) == 0 {
		t.Fatal("expected at least one row")
	}

	r := rows[0]
	if r.AccountID != "danskebank_ios_sample" {
		t.Errorf("AccountID = %q", r.AccountID)
	}
	if r.Currency != "DKK" {
		t.Errorf("Currency = %q, want DKK", r.Currency)
	}
	// First row: 18.06.2026;;;Netflix.Com;-149,00
	wantDate := time.Date(2026, 6, 18, 0, 0, 0, 0, time.UTC)
	if !r.Date.Equal(wantDate) {
		t.Errorf("first row Date = %v, want %v", r.Date, wantDate)
	}
	if r.Description != "Netflix.Com" {
		t.Errorf("Description = %q, want %q", r.Description, "Netflix.Com")
	}
	if r.AmountMinor != -14900 {
		t.Errorf("AmountMinor = %d, want -14900", r.AmountMinor)
	}

	// Income row should parse as positive
	income := rows[len(rows)-1]
	if income.AmountMinor != 2500000 {
		t.Errorf("income AmountMinor = %d, want 2500000", income.AmountMinor)
	}
}

func TestParseDanskeBank_ArchivedFilename(t *testing.T) {
	got := archivedPrefix.ReplaceAllString("20260514T155959Z_salary.csv", "")
	if got != "salary.csv" {
		t.Errorf("archivedPrefix strip: got %q, want %q", got, "salary.csv")
	}
}

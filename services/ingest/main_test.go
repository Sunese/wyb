package main

import (
	"testing"
	"time"
)

func TestParseDropFilename(t *testing.T) {
	cases := []struct {
		input       string
		wantBank    string
		wantAccount string
		wantID      string
		wantErr     bool
	}{
		{"danskebank_salary_20250101_20251231.csv", "danskebank", "salary", "danskebank_salary", false},
		{"danskebank_savings_20250101_20251231.csv", "danskebank", "savings", "danskebank_savings", false},
		{"danskebank_salary.csv", "danskebank", "salary", "danskebank_salary", false},
		{"noseparator.csv", "", "", "", true},
		{"_emptybank.csv", "", "", "", true},
	}

	for _, c := range cases {
		t.Run(c.input, func(t *testing.T) {
			got, err := parseDropFilename(c.input)
			if c.wantErr {
				if err == nil {
					t.Fatalf("expected error, got none")
				}
				return
			}
			if err != nil {
				t.Fatalf("unexpected error: %v", err)
			}
			if got.BankName != c.wantBank || got.AccountName != c.wantAccount || got.AccountID != c.wantID {
				t.Errorf("got {%s %s %s}, want {%s %s %s}",
					got.BankName, got.AccountName, got.AccountID,
					c.wantBank, c.wantAccount, c.wantID)
			}
		})
	}
}

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

func TestDanskeParserDetectHeader(t *testing.T) {
	p := &danskeParser{}

	if !p.DetectHeader([]string{"Dato", "Tekst", "Beløb", "Saldo", "Status", "Afstemt"}) {
		t.Error("should detect valid Danske Bank header")
	}
	if p.DetectHeader([]string{"Date", "Description", "Amount"}) {
		t.Error("should not detect unknown header")
	}
}

func TestParseDanskeBank(t *testing.T) {
	rows, err := ParseFile("../../testdata/danskebank_salary_20250101_20251231.csv")
	if err != nil {
		t.Fatalf("ParseFile: %v", err)
	}
	if len(rows) == 0 {
		t.Fatal("expected at least one row")
	}

	r := rows[0]
	if r.AccountID != "danskebank_salary" {
		t.Errorf("AccountID = %q, want %q", r.AccountID, "danskebank_salary")
	}
	if r.Currency != "DKK" {
		t.Errorf("Currency = %q, want DKK", r.Currency)
	}
	if r.Date.IsZero() {
		t.Error("Date should not be zero")
	}
	if r.Date.Year() < 2020 {
		t.Errorf("Date looks wrong: %v", r.Date)
	}
	wantDate := time.Date(2026, 5, 4, 0, 0, 0, 0, time.UTC)
	if !r.Date.Equal(wantDate) {
		t.Errorf("first row Date = %v, want %v", r.Date, wantDate)
	}
	if r.AmountMinor != 350000 {
		t.Errorf("AmountMinor = %d, want 350000", r.AmountMinor)
	}
}

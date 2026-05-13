package main

import (
	"bytes"
	"encoding/csv"
	"fmt"
	"io"
	"math"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"
	"unicode/utf8"

	"golang.org/x/text/encoding/charmap"
)

// Row is the normalised output of any bank parser.
type Row struct {
	AccountID   string
	Date        time.Time
	AmountMinor int64
	Currency    string
	Description string
	SourceFile  string
	RowIndex    int
}

// DropFilename is a parsed representation of the required drop filename convention.
// Format: bankName_accountName_fromDate_toDate.csv
// Example: danskebank_salary_20250101_20251231.csv
type DropFilename struct {
	BankName    string // e.g. "danskebank"
	AccountName string // user-defined label, e.g. "salary" — must be stable across exports
	AccountID   string // bankName_accountName — used as the dedup account identifier
}

func parseDropFilename(name string) (DropFilename, error) {
	base := strings.TrimSuffix(name, filepath.Ext(name))
	parts := strings.SplitN(base, "_", 3) // at most 3: bankName, accountName, rest
	if len(parts) < 2 {
		return DropFilename{}, fmt.Errorf(
			"filename %q does not match expected format: bankName_accountName_fromDate_toDate.csv",
			name,
		)
	}
	bank := strings.ToLower(strings.TrimSpace(parts[0]))
	account := strings.ToLower(strings.TrimSpace(parts[1]))
	if bank == "" || account == "" {
		return DropFilename{}, fmt.Errorf("filename %q: bankName and accountName must not be empty", name)
	}
	return DropFilename{
		BankName:    bank,
		AccountName: account,
		AccountID:   bank + "_" + account,
	}, nil
}

// BankParser parses a specific bank's CSV export.
type BankParser interface {
	// BankName returns the canonical lowercase bank identifier used in filenames.
	BankName() string
	// DetectHeader sanity-checks that the file header matches expectations.
	// Headers are already decoded to UTF-8 and trimmed of whitespace.
	DetectHeader(header []string) bool
	// Parse reads all data rows from r and returns normalised rows.
	Parse(r io.Reader, sourceName, accountID string) ([]Row, error)
}

// registry maps lowercase bank name → parser.
var registry = map[string]BankParser{
	"danskebank": &danskeParser{},
}

// ParseFile parses path using the filename convention to identify the bank and account.
func ParseFile(path string) ([]Row, error) {
	meta, err := parseDropFilename(filepath.Base(path))
	if err != nil {
		return nil, err
	}

	parser, ok := registry[meta.BankName]
	if !ok {
		supported := make([]string, 0, len(registry))
		for k := range registry {
			supported = append(supported, k)
		}
		return nil, fmt.Errorf("unsupported bank %q (supported: %s)", meta.BankName, strings.Join(supported, ", "))
	}

	data, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("read: %w", err)
	}

	decoded, err := decodeToUTF8(data)
	if err != nil {
		return nil, fmt.Errorf("decode: %w", err)
	}

	header, err := sniffHeader(decoded)
	if err != nil {
		return nil, fmt.Errorf("sniff header: %w", err)
	}

	if !parser.DetectHeader(header) {
		return nil, fmt.Errorf("file header does not match expected %s format", parser.BankName())
	}

	rows, err := parser.Parse(bytes.NewReader(decoded), filepath.Base(path), meta.AccountID)
	if err != nil {
		return nil, fmt.Errorf("%s: %w", parser.BankName(), err)
	}
	return rows, nil
}

// decodeToUTF8 detects and converts the byte slice to UTF-8.
// Strategy: UTF-8 BOM → strip and return; valid UTF-8 → return as-is;
// otherwise assume Windows-1252 (most common for European bank exports).
func decodeToUTF8(data []byte) ([]byte, error) {
	if bytes.HasPrefix(data, []byte{0xEF, 0xBB, 0xBF}) {
		return data[3:], nil
	}
	if utf8.Valid(data) {
		return data, nil
	}
	decoded, err := charmap.Windows1252.NewDecoder().Bytes(data)
	if err != nil {
		return nil, fmt.Errorf("windows-1252 decode failed: %w", err)
	}
	return decoded, nil
}

// sniffHeader reads the first line and tries common CSV delimiters.
func sniffHeader(data []byte) ([]string, error) {
	for _, delim := range []rune{';', ',', '\t'} {
		r := csv.NewReader(bytes.NewReader(data))
		r.Comma = delim
		record, err := r.Read()
		if err != nil {
			continue
		}
		if len(record) > 1 {
			for i, f := range record {
				record[i] = strings.TrimSpace(f)
			}
			return record, nil
		}
	}
	return nil, fmt.Errorf("could not determine delimiter")
}

// ── Danske Bank ──────────────────────────────────────────────────────────────

type danskeParser struct{}

func (d *danskeParser) BankName() string { return "danskebank" }

func (d *danskeParser) DetectHeader(header []string) bool {
	if len(header) < 3 {
		return false
	}
	// Danske Bank exports "Beløb" but their exporter sometimes emits U+FFFD
	// in place of ø, so we match on the stable ASCII parts only.
	col2 := strings.ToLower(header[2])
	return strings.EqualFold(header[0], "Dato") &&
		strings.EqualFold(header[1], "Tekst") &&
		strings.HasPrefix(col2, "bel") && strings.HasSuffix(col2, "b")
}

func (d *danskeParser) Parse(r io.Reader, sourceName, accountID string) ([]Row, error) {
	cr := csv.NewReader(r)
	cr.Comma = ';'

	if _, err := cr.Read(); err != nil {
		return nil, fmt.Errorf("read header: %w", err)
	}

	var rows []Row
	for rowIndex := 0; ; rowIndex++ {
		record, err := cr.Read()
		if err == io.EOF {
			break
		}
		if err != nil {
			return nil, fmt.Errorf("row %d: %w", rowIndex, err)
		}
		if len(record) < 3 {
			continue
		}

		date, err := time.Parse("02.01.2006", strings.TrimSpace(record[0]))
		if err != nil {
			return nil, fmt.Errorf("row %d: date %q: %w", rowIndex, record[0], err)
		}
		amount, err := parseDanishAmount(record[2])
		if err != nil {
			return nil, fmt.Errorf("row %d: amount %q: %w", rowIndex, record[2], err)
		}

		rows = append(rows, Row{
			AccountID:   accountID,
			Date:        date,
			AmountMinor: amount,
			Currency:    "DKK",
			Description: strings.TrimSpace(record[1]),
			SourceFile:  sourceName,
			RowIndex:    rowIndex,
		})
	}

	return rows, nil
}

// ── Helpers ───────────────────────────────────────────────────────────────────

// parseDanishAmount converts "-3.842,00" → -384200 øre.
func parseDanishAmount(s string) (int64, error) {
	s = strings.TrimSpace(s)
	s = strings.ReplaceAll(s, ".", "")
	s = strings.ReplaceAll(s, ",", ".")
	f, err := strconv.ParseFloat(s, 64)
	if err != nil {
		return 0, err
	}
	return int64(math.Round(f * 100)), nil
}

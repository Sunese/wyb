package main

import (
	"bytes"
	"encoding/csv"
	"fmt"
	"io"
	"math"
	"os"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"time"
	"unicode/utf8"

	"golang.org/x/text/encoding/charmap"
)

// archivedPrefix matches the timestamp prepended when a drop file is archived to raw/.
// Format: YYYYMMDDTHHMMSSZ_ e.g. "20260514T155959Z_"
var archivedPrefix = regexp.MustCompile(`^\d{8}T\d{6}Z_`)

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

// BankParser parses a specific bank's CSV export.
type BankParser interface {
	// BankName returns the canonical lowercase bank identifier.
	BankName() string
	// DetectHeader returns true if the header row matches this bank's format.
	// Headers are already decoded to UTF-8 and trimmed of whitespace.
	DetectHeader(header []string) bool
	// Parse reads all data rows from r and returns normalised rows.
	Parse(r io.Reader, sourceName, accountID string) ([]Row, error)
}

// registry holds all registered bank parsers. More-specific variants first so
// DetectHeader matching is unambiguous when headers share a prefix.
var registry = []BankParser{
	&danskeIosParser{},
	&danskeDesktopParser{},
}

// ParseFile auto-detects the bank format from file content and parses the file.
// The account ID is derived from the filename stem — users name their files
// consistently (e.g. "salary.csv") so the ID is stable across imports.
// Archived files (prefixed with a timestamp by the watcher) are handled transparently.
func ParseFile(path string) ([]Row, error) {
	base := archivedPrefix.ReplaceAllString(filepath.Base(path), "")
	accountID := strings.TrimSuffix(base, filepath.Ext(base))

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

	parser := detectParser(header)
	if parser == nil {
		return nil, fmt.Errorf("unrecognised file format: no registered bank parser matched the header")
	}

	rows, err := parser.Parse(bytes.NewReader(decoded), filepath.Base(path), accountID)
	if err != nil {
		return nil, fmt.Errorf("%s: %w", parser.BankName(), err)
	}
	return rows, nil
}

// detectParser returns the first registered parser whose DetectHeader matches,
// or nil if none match.
func detectParser(header []string) BankParser {
	for _, p := range registry {
		if p.DetectHeader(header) {
			return p
		}
	}
	return nil
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

// isBelob returns true for the "Beløb" column header, tolerating the ø/U+FFFD
// substitution that Danske's exporter sometimes emits.
func isBelob(s string) bool {
	s = strings.ToLower(s)
	return strings.HasPrefix(s, "bel") && strings.HasSuffix(s, "b")
}

// parseDanskeCSV is the shared CSV reading loop for both Danske parsers.
// minCols is the minimum number of fields required per data row.
// descIdx and amountIdx are the zero-based column positions of description and amount.
func parseDanskeCSV(r io.Reader, sourceName, accountID string, minCols, descIdx, amountIdx int) ([]Row, error) {
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
		if len(record) < minCols {
			continue
		}

		date, err := time.Parse("02.01.2006", strings.TrimSpace(record[0]))
		if err != nil {
			return nil, fmt.Errorf("row %d: date %q: %w", rowIndex, record[0], err)
		}
		amount, err := parseDanishAmount(record[amountIdx])
		if err != nil {
			return nil, fmt.Errorf("row %d: amount %q: %w", rowIndex, record[amountIdx], err)
		}

		rows = append(rows, Row{
			AccountID:   accountID,
			Date:        date,
			AmountMinor: amount,
			Currency:    "DKK",
			Description: strings.TrimSpace(record[descIdx]),
			SourceFile:  sourceName,
			RowIndex:    rowIndex,
		})
	}
	return rows, nil
}

// ── Danske Bank — desktop export ──────────────────────────────────────────────
// Header: Dato;Tekst;Beløb;Saldo;Status;Afstemt   (values are double-quoted)

type danskeDesktopParser struct{}

func (d *danskeDesktopParser) BankName() string { return "danskebank-desktop" }

func (d *danskeDesktopParser) DetectHeader(header []string) bool {
	return len(header) >= 3 &&
		strings.EqualFold(header[0], "Dato") &&
		strings.EqualFold(header[1], "Tekst") &&
		isBelob(header[2])
}

func (d *danskeDesktopParser) Parse(r io.Reader, sourceName, accountID string) ([]Row, error) {
	// col 0: Dato, col 1: Tekst, col 2: Beløb
	return parseDanskeCSV(r, sourceName, accountID, 3, 1, 2)
}

// ── Danske Bank — iOS export ──────────────────────────────────────────────────
// Header: Dato;Kategori;Underkategori;Tekst;Beløb;Saldo;Status;Afstemt
// Values are not quoted. Two bank-category columns precede Tekst.

type danskeIosParser struct{}

func (d *danskeIosParser) BankName() string { return "danskebank-ios" }

func (d *danskeIosParser) DetectHeader(header []string) bool {
	return len(header) >= 5 &&
		strings.EqualFold(header[0], "Dato") &&
		strings.EqualFold(header[1], "Kategori") &&
		strings.EqualFold(header[2], "Underkategori") &&
		strings.EqualFold(header[3], "Tekst") &&
		isBelob(header[4])
}

func (d *danskeIosParser) Parse(r io.Reader, sourceName, accountID string) ([]Row, error) {
	// col 0: Dato, col 3: Tekst, col 4: Beløb
	return parseDanskeCSV(r, sourceName, accountID, 5, 3, 4)
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

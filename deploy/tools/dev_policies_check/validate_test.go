// This test proves that the kit's development policies
// (tools/dev_policies.json) are documents KulOffice accepts: each one is run
// through the validator its product registers. It lives in the kit and is
// compiled inside a KulOffice checkout by check.sh, as an external test of
// internal/businesspolicy (go test -overlay), since those validators are
// KulOffice internals.
package businesspolicy_test

import (
	"encoding/json"
	"os"
	"slices"
	"testing"

	"github.com/pavulla-tech/kuloffice/internal/businesspolicy"

	_ "github.com/pavulla-tech/kuloffice/internal/accountlimit"
	_ "github.com/pavulla-tech/kuloffice/internal/agents"
	_ "github.com/pavulla-tech/kuloffice/internal/budget"
	_ "github.com/pavulla-tech/kuloffice/internal/claimsend"
	_ "github.com/pavulla-tech/kuloffice/internal/fleet"
	_ "github.com/pavulla-tech/kuloffice/internal/merchantcollections"
	_ "github.com/pavulla-tech/kuloffice/internal/notification"
	_ "github.com/pavulla-tech/kuloffice/internal/orientu"
	_ "github.com/pavulla-tech/kuloffice/internal/paymentterms"
	_ "github.com/pavulla-tech/kuloffice/internal/vaquinha"
)

type file struct {
	Policies []struct {
		Key      string          `json:"key"`
		Document json.RawMessage `json:"document"`
	} `json:"policies"`
}

func load(t *testing.T) file {
	t.Helper()
	path := os.Getenv("DEV_POLICIES")
	if path == "" {
		t.Fatal("DEV_POLICIES names the kit's tools/dev_policies.json")
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var f file
	if err := json.Unmarshal(raw, &f); err != nil {
		t.Fatal(err)
	}
	return f
}

func TestEveryDevPolicyValidates(t *testing.T) {
	validators := map[string]func([]byte) error{}
	for _, d := range businesspolicy.Definitions() {
		validators[d.Key] = d.Validate
	}
	seen := map[string]bool{}
	for _, p := range load(t).Policies {
		if seen[p.Key] {
			t.Errorf("%s appears twice", p.Key)
		}
		seen[p.Key] = true
		validate, ok := validators[p.Key]
		if !ok {
			t.Errorf("%s is not a policy KulOffice registers", p.Key)
			continue
		}
		if err := validate(p.Document); err != nil {
			t.Errorf("%s: %v", p.Key, err)
		}
	}
	for key := range validators {
		if !seen[key] {
			t.Errorf("KulOffice registers %s, which tools/dev_policies.json does not seed", key)
		}
	}
}

// What the development stack needs from them beyond being valid.
func TestDevPoliciesSwitchTheProductsOn(t *testing.T) {
	docs := map[string]map[string]any{}
	for _, p := range load(t).Policies {
		var d map[string]any
		if err := json.Unmarshal(p.Document, &d); err != nil {
			t.Fatal(err)
		}
		docs[p.Key] = d
	}
	var purposes []string
	for _, v := range docs["merchant_collections"]["purposes"].([]any) {
		purposes = append(purposes, v.(string))
	}
	for _, want := range []string{"shop", "online_shop", "integration", "agent_commissions", "other"} {
		if !slices.Contains(purposes, want) {
			t.Errorf("merchant_collections.purposes lacks %s", want)
		}
	}
	services := docs["agents"]["services"].(map[string]any)
	for _, s := range []string{"S1", "S2", "S4", "S5", "S6", "S8"} {
		if _, ok := services[s]; !ok {
			t.Errorf("agents.services lacks %s", s)
		}
	}
	for s, rules := range services {
		if _, ok := rules.(map[string]any)["activation_max_minor"]; ok != (s == "S1") {
			t.Errorf("agents.services.%s: activation_max_minor is S1's only", s)
		}
	}
	if v := docs["devices"]["terminal"].(map[string]any)["min_app_version"]; v != "" {
		t.Errorf("devices.terminal.min_app_version is empty on development stacks, not %v", v)
	}
	for _, key := range []string{"claim_send", "agents", "vaquinha", "budgets"} {
		if docs[key]["enabled"] != true {
			t.Errorf("%s is enabled on development stacks", key)
		}
		if docs[key]["notification_language"] != "pt" {
			t.Errorf("%s.notification_language is pt (the dev texts' language)", key)
		}
	}
}

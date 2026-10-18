package substrate

import (
	"testing"

	"go.ate.dev/substrate/pkg/proto/ateapipb"
)

func TestActorDurableSnapshotSelectsNewestCompletedCopy(t *testing.T) {
	older := NewDurableSnapshot("s3://snapshots/old", ateapipb.SnapshotFidelity_SNAPSHOT_FIDELITY_VOLUMES, "template")
	older.Generation = 1
	newer := NewDurableSnapshot("s3://snapshots/new", ateapipb.SnapshotFidelity_SNAPSHOT_FIDELITY_MEMORY, "template")
	newer.Generation = 2
	pending := NewDurableSnapshot("s3://snapshots/pending", ateapipb.SnapshotFidelity_SNAPSHOT_FIDELITY_MEMORY, "template")
	pending.Generation = 3
	pending.DurableSnapshot.Status = ateapipb.SnapshotStorageStatus_SNAPSHOT_STORAGE_STATUS_PENDING
	actor := &ateapipb.Actor{Status: &ateapipb.ActorStatus{Snapshots: []*ateapipb.Snapshot{older, pending, newer}}}

	got := ActorDurableSnapshot(actor)
	if SnapshotURI(got) != "s3://snapshots/new" {
		t.Fatalf("snapshot URI = %q", SnapshotURI(got))
	}
	scope, ok := SnapshotContentScope(got)
	if !ok || scope != ContentScopeFull {
		t.Fatalf("content scope = %q, ok = %v", scope, ok)
	}
}

func TestContentScopeNameRejectsRootfs(t *testing.T) {
	if scope, ok := ContentScopeName(ateapipb.SnapshotFidelity_SNAPSHOT_FIDELITY_ROOTFS); ok || scope != "" {
		t.Fatalf("rootfs scope = %q, ok = %v", scope, ok)
	}
}

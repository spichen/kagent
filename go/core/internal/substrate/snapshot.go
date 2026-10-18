package substrate

import "go.ate.dev/substrate/pkg/proto/ateapipb"

// Content-scope names stored for a session snapshot. PostgreSQL accepts only
// these two. MEMORY includes process state, so it is FULL and cannot be
// forked. VOLUMES is the durable directory only, so it is DATA.
const (
	ContentScopeFull = "FULL"
	ContentScopeData = "DATA"
)

// ContentScopeName maps a Substrate snapshot fidelity onto the stored name.
func ContentScopeName(fidelity ateapipb.SnapshotFidelity) (string, bool) {
	switch fidelity {
	case ateapipb.SnapshotFidelity_SNAPSHOT_FIDELITY_MEMORY:
		return ContentScopeFull, true
	case ateapipb.SnapshotFidelity_SNAPSHOT_FIDELITY_VOLUMES:
		return ContentScopeData, true
	default:
		return "", false
	}
}

// SnapshotContentScope reports the stored name of a completed snapshot.
func SnapshotContentScope(snapshot *ateapipb.Snapshot) (string, bool) {
	if snapshot == nil {
		return "", false
	}
	return ContentScopeName(snapshot.GetFidelity())
}

// SnapshotURI returns the object-storage URI of a snapshot's durable copy.
func SnapshotURI(snapshot *ateapipb.Snapshot) string {
	return snapshot.GetDurableSnapshot().GetObject().GetSnapshotUri()
}

// ActorDurableSnapshot returns the actor's newest completed snapshot.
func ActorDurableSnapshot(actor *ateapipb.Actor) *ateapipb.Snapshot {
	var best *ateapipb.Snapshot
	for _, snapshot := range actor.GetStatus().GetSnapshots() {
		if snapshot.GetOwner() != ateapipb.SnapshotOwner_SNAPSHOT_OWNER_ACTOR || !snapshotComplete(snapshot) {
			continue
		}
		if best == nil || snapshot.GetGeneration() > best.GetGeneration() {
			best = snapshot
		}
	}
	return best
}

// TagDurableSnapshot returns the tag's snapshot once its durable copy is complete.
func TagDurableSnapshot(tag *ateapipb.Tag) *ateapipb.Snapshot {
	snapshot := tag.GetStatus().GetSnapshot()
	if !snapshotComplete(snapshot) {
		return nil
	}
	return snapshot
}

// NewDurableSnapshot builds a completed snapshot for tests and fixtures.
func NewDurableSnapshot(uri string, fidelity ateapipb.SnapshotFidelity, templateUID string) *ateapipb.Snapshot {
	return &ateapipb.Snapshot{
		Uuid:             "snapshot",
		Generation:       1,
		Owner:            ateapipb.SnapshotOwner_SNAPSHOT_OWNER_ACTOR,
		Fidelity:         fidelity,
		ActorTemplateUid: templateUID,
		DurableSnapshot: &ateapipb.SnapshotStorage{
			Status: ateapipb.SnapshotStorageStatus_SNAPSHOT_STORAGE_STATUS_COMPLETED,
			Object: &ateapipb.ObjectSnapshot{SnapshotUri: uri},
		},
	}
}

func snapshotComplete(snapshot *ateapipb.Snapshot) bool {
	storage := snapshot.GetDurableSnapshot()
	return storage.GetStatus() == ateapipb.SnapshotStorageStatus_SNAPSHOT_STORAGE_STATUS_COMPLETED && storage.GetObject().GetSnapshotUri() != ""
}

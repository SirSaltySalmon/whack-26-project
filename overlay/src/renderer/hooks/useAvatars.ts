import { useEffect, useRef, useState } from "react";
import { logger } from "../../lib/logger.ts";
import catUrl from "../assets/avatar-cat.png";
import {
  AvatarImageError,
  readAvatarSource,
  renderAvatar,
} from "../lib/avatarImage.ts";
import {
  announceAvatarChange,
  deleteUpload,
  listUploads,
  onAvatarChange,
  saveUpload,
} from "../lib/avatarStore.ts";
import {
  legacyAvatarImage,
  savedAvatarChoice,
  savedRemoveBackground,
} from "../lib/storage.ts";
import {
  cleanName,
  DEFAULT_AVATAR_ID,
  effectiveChoice,
  lookFor,
  nameFromFile,
  needsRecut,
  sortUploads,
  uniqueName,
  type AvatarEdits,
  type AvatarLook,
  type UploadedAvatar,
} from "../logic/avatars.ts";

export type AvatarChanges = Partial<AvatarEdits> & { name?: string };

export interface Avatars {
  /** The chosen avatar's id: a built-in's, or an upload's. */
  choice: string;
  look: AvatarLook;
  /** Null until they've loaded. */
  uploads: UploadedAvatar[] | null;
  /** Whether new uploads get their white background removed. */
  removeBackground: boolean;
  busy: boolean;
  error: string | null;
  choose(id: string): void;
  upload(file: File): void;
  edit(id: string, changes: AvatarChanges): void;
  remove(id: string): void;
  setRemoveBackground(remove: boolean): void;
}

const LEGACY_ID = "legacy-upload";

/** The one picture saved before the gallery existed becomes its first upload, still chosen. */
async function moveLegacyImage(): Promise<void> {
  const image = legacyAvatarImage.load();
  if (image === null) return;
  // A fixed id, so both windows moving it at once write the same record.
  await saveUpload({
    id: LEGACY_ID,
    name: "My avatar",
    createdAt: Date.now(),
    source: image,
    image,
    removeBackground: false,
    mirrored: false,
  });
  savedAvatarChoice.save(LEGACY_ID);
  legacyAvatarImage.clear();
  announceAvatarChange();
}

/**
 * The avatar gallery, shared by the overlay and the Control Center: either window can change it
 * and the other follows. Uploads never leave this machine.
 */
export function useAvatars(): Avatars {
  const [choice, setChoice] = useState(savedAvatarChoice.load);
  const [uploads, setUploads] = useState<UploadedAvatar[] | null>(null);
  const [removeBackground, setRemove] = useState(savedRemoveBackground.load);
  const [pending, setPending] = useState(0);
  const [error, setError] = useState<string | null>(null);
  // Queued work reads the newest list from here, since state only updates on the next render.
  const list = useRef<UploadedAvatar[] | null>(null);
  // One change at a time, so two quick edits to one avatar can't overwrite each other.
  const queue = useRef<Promise<void>>(Promise.resolve());

  const setList = (next: UploadedAvatar[] | null): void => {
    list.current = next;
    setUploads(next);
  };

  useEffect(() => {
    let alive = true;
    const reload = (): void => {
      setChoice(savedAvatarChoice.load());
      setRemove(savedRemoveBackground.load());
      listUploads()
        .then((loaded) => {
          if (alive) setList(sortUploads(loaded));
        })
        .catch((reason: unknown) => {
          logger.warn("Could not load the uploaded avatars", reason);
          if (!alive) return;
          setList(list.current ?? []);
          setError("Couldn't load your uploaded avatars.");
        });
    };
    moveLegacyImage()
      .catch((reason: unknown) =>
        logger.warn("Could not move the old avatar into the gallery", reason),
      )
      .finally(reload);
    const stop = onAvatarChange(reload);
    return () => {
      alive = false;
      stop();
    };
  }, []);

  const enqueue = (work: () => Promise<void>, failure: string): void => {
    setPending((count) => count + 1);
    setError(null);
    queue.current = queue.current
      .then(work)
      .catch((reason: unknown) => {
        logger.warn(failure, reason);
        setError(reason instanceof AvatarImageError ? reason.message : failure);
      })
      .finally(() => setPending((count) => count - 1));
  };

  const choose = (id: string): void => {
    savedAvatarChoice.save(id);
    setChoice(id);
    setError(null);
    announceAvatarChange();
  };

  return {
    choice: effectiveChoice(choice, uploads),
    look: lookFor(choice, uploads, catUrl),
    uploads,
    removeBackground,
    busy: pending > 0,
    error,
    choose,
    upload(file) {
      const edits = { removeBackground, mirrored: false };
      enqueue(async () => {
        const source = await readAvatarSource(file);
        const image = await renderAvatar(source, edits);
        const current = list.current ?? [];
        const avatar: UploadedAvatar = {
          id: crypto.randomUUID(),
          name: uniqueName(
            nameFromFile(file.name),
            current.map((other) => other.name),
          ),
          createdAt: Date.now(),
          source,
          image,
          ...edits,
        };
        await saveUpload(avatar);
        setList([...current, avatar]);
        choose(avatar.id);
      }, "Couldn't save that avatar.");
    },
    edit(id, changes) {
      enqueue(async () => {
        const current = list.current?.find((avatar) => avatar.id === id);
        if (current === undefined) return;
        const next: UploadedAvatar = {
          ...current,
          ...changes,
          name:
            changes.name === undefined
              ? current.name
              : cleanName(changes.name, current.name),
        };
        const recut = needsRecut(current, next);
        if (!recut && next.name === current.name) return;
        if (recut) next.image = await renderAvatar(next.source, next);
        await saveUpload(next);
        setList(
          (list.current ?? []).map((avatar) =>
            avatar.id === id ? next : avatar,
          ),
        );
        announceAvatarChange();
      }, "Couldn't change that avatar.");
    },
    remove(id) {
      enqueue(async () => {
        await deleteUpload(id);
        setList((list.current ?? []).filter((avatar) => avatar.id !== id));
        if (savedAvatarChoice.load() === id) {
          savedAvatarChoice.save(DEFAULT_AVATAR_ID);
          setChoice(DEFAULT_AVATAR_ID);
        }
        announceAvatarChange();
      }, "Couldn't delete that avatar.");
    },
    setRemoveBackground(remove) {
      savedRemoveBackground.save(remove);
      setRemove(remove);
      announceAvatarChange();
    },
  };
}

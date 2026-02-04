"use client";

import { useMemo, ReactNode } from "react";

export default function FileSlot({
                                     title,
                                     required,
                                     accept,
                                     file,
                                     disabled,
                                     onChangeFile,
                                     onClear,
                                     labels,
                                     extraRight,
                                 }: {
    title: string;
    required?: boolean;
    accept: string;
    file: File | null;
    disabled: boolean;
    onChangeFile: (f: File | null) => void;
    onClear: () => void;
    labels?: {
        required?: string;
        none?: string;
        remove?: string;
        add?: string;
        replace?: string;
        hint?: string;
    };
    extraRight?: ReactNode;
}) {
    const inputId = useMemo(
        () =>
            `file_${title.replace(/\s+/g, "_").toLowerCase()}_${Math.random()
                .toString(16)
                .slice(2)}`,
        [title]
    );

    return (
        <div
            className="rounded-2xl border p-2 shadow-sm"
            style={{
                background: file ? "var(--surface-strong)" : "var(--surface)",
                borderColor: file ? "var(--chat-bot-border)" : "var(--surface-border)",
                boxShadow: file ? "var(--shadow-press)" : "var(--shadow-soft)",
            }}
        >
            {/* Header ultra compact */}
            <div className="flex items-center justify-between gap-2">
                <div className="min-w-0">
                    <div className="flex items-center gap-1.5">
                        <div className="text-[12px] font-semibold truncate" style={{ color: "var(--text-dark)" }}>
                            {title}
                        </div>
                        {required ? (
                            <span className="text-[10px] whitespace-nowrap" style={{ color: "var(--accent-orange)" }}>
                                {labels?.required ?? "• obligatoire"}
                            </span>
                        ) : null}
                    </div>

                    <div className="text-[10px] truncate mt-0.5" style={{ color: "var(--text-muted)" }}>
                        {file ? (
                            <>
                                ✅ <span className="font-medium" style={{ color: "var(--text-dark)" }}>{file.name}</span>
                            </>
                        ) : (
                            <span>{labels?.none ?? "Aucun fichier"}</span>
                        )}
                    </div>
                </div>

                <div className="flex items-center gap-2">
                    {extraRight ? <div className="shrink-0">{extraRight}</div> : null}
                    {file ? (
                        <button
                            type="button"
                            onClick={onClear}
                            disabled={disabled}
                            className="shrink-0 text-[10px] px-2 py-1 rounded-full border transition disabled:opacity-60"
                            style={{ background: "var(--surface-strong)", borderColor: "var(--surface-border)", color: "var(--text-dark)" }}
                            title={labels?.remove ?? "Retirer"}
                        >
                            {labels?.remove ?? "Retirer"}
                        </button>
                    ) : null}
                </div>
            </div>

            {/* Actions sur une seule ligne */}
            <div className="mt-2 flex items-center gap-2">
                <input
                    id={inputId}
                    type="file"
                    accept={accept}
                    disabled={disabled}
                    onChange={(e) => onChangeFile(e.target.files?.[0] ?? null)}
                    className="hidden"
                />

                <label
                    htmlFor={inputId}
                    className={`inline-flex items-center justify-center cursor-pointer select-none text-[10px] px-3 py-1.5 rounded-full border shadow-sm transition whitespace-nowrap ${disabled ? "cursor-not-allowed opacity-60" : "hover:brightness-105"}`}
                    style={{ background: "var(--surface-strong)", borderColor: "var(--surface-border)", color: "var(--text-dark)", boxShadow: "var(--shadow-press)" }}
                >
                    {file ? labels?.replace ?? "Remplacer" : labels?.add ?? "Ajouter"}
                </label>

                <span className="text-[10px] truncate" style={{ color: "var(--text-muted)" }}>{labels?.hint ?? "PDF / photo"}</span>
            </div>
        </div>
    );
}

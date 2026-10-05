import React from 'react';
import Skeleton from './Skeleton';
import SkeletonMessage from './SkeletonMessage';
import SkeletonConversationItem from './SkeletonConversationItem';

export default function SkeletonChatWorkspace() {
  return (
    <div className="flex h-screen w-screen overflow-hidden bg-[#c5d0dd]">
      {/* Left Sidebar Skeleton */}
      <div className="z-20 hidden md:flex w-[300px] shrink-0 flex-col border-r border-slate-300/50 bg-white shadow-[6px_0_32px_rgba(15,23,42,0.06)]">
        <div className="flex h-[72px] items-center justify-between border-b border-slate-200/90 px-5">
          <div className="flex items-center gap-3">
            <Skeleton variant="rounded" className="h-9 w-9 rounded-xl" />
            <div className="space-y-1">
              <Skeleton variant="text" className="h-3 w-28" />
              <Skeleton variant="text" className="h-2 w-16" />
            </div>
          </div>
        </div>

        <div className="p-3 border-b border-slate-200/90">
          <Skeleton variant="rounded" className="h-10 w-full rounded-xl" />
        </div>

        <div className="flex-1 p-3 space-y-2 overflow-y-auto">
          <SkeletonConversationItem />
          <SkeletonConversationItem />
          <SkeletonConversationItem />
          <SkeletonConversationItem />
          <SkeletonConversationItem />
        </div>

        <div className="border-t border-slate-200/90 p-4">
          <Skeleton variant="rounded" className="h-10 w-full rounded-xl" />
        </div>
      </div>

      {/* Main Chat Workspace Skeleton */}
      <div className="flex min-h-0 min-w-0 flex-1 flex-col p-2 sm:p-2.5">
        <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-2xl border border-white/70 bg-white shadow-[0_28px_90px_rgba(15,23,42,0.14)] ring-1 ring-slate-200/80">
          {/* Header */}
          <div className="shrink-0 border-b border-slate-200/90 bg-white px-4 py-3 sm:px-6">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <Skeleton variant="rounded" className="h-10 w-10 rounded-xl" />
                <div className="space-y-1.5">
                  <Skeleton variant="text" className="h-4 w-36" />
                  <Skeleton variant="text" className="h-2.5 w-24" />
                </div>
              </div>
              <div className="flex items-center gap-2">
                <Skeleton variant="rounded" className="h-7 w-20 rounded-lg" />
                <Skeleton variant="rounded" className="h-7 w-16 rounded-lg" />
              </div>
            </div>
          </div>

          {/* Messages Body */}
          <div className="flex-1 overflow-y-auto p-6 space-y-6 bg-section-bg/40">
            <SkeletonMessage sender="user" />
            <SkeletonMessage sender="ai" />
            <SkeletonMessage sender="user" />
            <SkeletonMessage sender="ai" />
          </div>

          {/* Composer Footer */}
          <div className="shrink-0 border-t border-slate-200/90 bg-white p-4">
            <Skeleton variant="rounded" className="h-12 w-full rounded-2xl" />
          </div>
        </div>
      </div>
    </div>
  );
}

import React from 'react';
import Skeleton from './Skeleton';

export default function SkeletonAgentCard({ variant = 'dashboard' }) {
  if (variant === 'catalog') {
    return (
      <div className="flex flex-col p-6 bg-white border border-border rounded-xl relative overflow-hidden shadow-xs">
        {/* Top: Icon + Badges */}
        <div className="flex items-start justify-between mb-4">
          <Skeleton variant="rounded" className="w-10 h-10 rounded-lg" />
          <div className="flex items-center gap-2">
            <Skeleton variant="rounded" className="w-16 h-5 rounded-full" />
            <Skeleton variant="rounded" className="w-12 h-5 rounded-full" />
          </div>
        </div>

        {/* Title & Purpose */}
        <Skeleton variant="text" className="h-5 w-3/5 mb-2.5" />
        <div className="space-y-1.5 mb-4 flex-1">
          <Skeleton variant="text" className="h-3.5 w-full" />
          <Skeleton variant="text" className="h-3.5 w-5/6" />
          <Skeleton variant="text" className="h-3.5 w-2/3" />
        </div>

        {/* Metadata pill */}
        <div className="mb-4">
          <Skeleton variant="rounded" className="h-8 w-full rounded-lg" />
        </div>

        {/* Footer actions */}
        <div className="pt-4 border-t border-border flex items-center justify-between">
          <Skeleton variant="rounded" className="h-7 w-16 rounded-xl" />
          <Skeleton variant="rounded" className="h-8 w-24 rounded-xl" />
        </div>
      </div>
    );
  }

  // Dashboard variant
  return (
    <div className="flex flex-col p-8 bg-white border border-border/60 rounded-[2.5rem] relative overflow-hidden shadow-xs">
      {/* Top: Avatar + Live Badge */}
      <div className="flex items-start justify-between mb-8">
        <Skeleton variant="rounded" className="w-14 h-14 rounded-2xl" />
        <Skeleton variant="rounded" className="w-16 h-6 rounded-full" />
      </div>

      {/* Middle: Title & Purpose */}
      <div className="flex-1 min-w-0 mb-6">
        <Skeleton variant="text" className="h-6 w-3/4 mb-3" />
        <div className="space-y-2">
          <Skeleton variant="text" className="h-4 w-full" />
          <Skeleton variant="text" className="h-4 w-2/3" />
        </div>
      </div>

      {/* Bottom: Date & Action icon */}
      <div className="flex items-center justify-between pt-6 border-t border-border/40">
        <Skeleton variant="text" className="h-3 w-20" />
        <Skeleton variant="circular" className="w-5 h-5" />
      </div>
    </div>
  );
}

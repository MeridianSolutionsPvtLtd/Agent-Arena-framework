import React from 'react';
import Skeleton from './Skeleton';

export default function SkeletonMessage({ sender = 'ai' }) {
  const isUser = sender === 'user';

  return (
    <div className={`flex gap-4 sm:gap-6 ${isUser ? 'flex-row-reverse' : ''} animate-in fade-in duration-300`}>
      {/* Avatar */}
      <Skeleton
        variant="rounded"
        className={`w-9 h-9 rounded-xl shrink-0 ${isUser ? 'bg-primary/20' : ''}`}
      />

      {/* Bubble + Metadata */}
      <div className={`flex flex-col ${isUser ? 'items-end' : 'items-start'} max-w-[80%] sm:max-w-[70%]`}>
        <div
          className={`p-5 rounded-3xl ${
            isUser
              ? 'bg-primary/10 rounded-tr-md w-64 sm:w-80'
              : 'bg-white border border-border/60 rounded-tl-md w-72 sm:w-96'
          } shadow-xs space-y-2`}
        >
          <Skeleton variant="text" className={`h-4 ${isUser ? 'w-5/6 ml-auto' : 'w-full'}`} />
          <Skeleton variant="text" className={`h-4 ${isUser ? 'w-3/5 ml-auto' : 'w-4/5'}`} />
          {!isUser && <Skeleton variant="text" className="h-4 w-1/2" />}
        </div>

        {/* Timestamp */}
        <div className="mt-2 px-2">
          <Skeleton variant="text" className="h-2.5 w-12" />
        </div>
      </div>
    </div>
  );
}

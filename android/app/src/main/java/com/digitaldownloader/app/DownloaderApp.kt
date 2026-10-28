package com.digitaldownloader.app

import android.app.Application

class DownloaderApp : Application() {
    override fun onCreate() {
        super.onCreate()
        Notifications.ensureChannels(this)
        Engine.warmUp(this)
    }
}
